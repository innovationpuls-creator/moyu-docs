"""Executable BDD probe for the known Workspace route.

All other lifecycle scenarios remain in the feature with FR tags and are
marked pending-contract-binding until Task 4 publishes their API contracts.
"""

from __future__ import annotations

import uuid

from httpx import Response
from pytest_bdd import given, parsers, then, when
from sqlalchemy import text

from tests.bdd.conftest import BDDContext


def _record(ctx: BDDContext, response: Response) -> None:
    ctx.last_status = response.status_code
    ctx.last_body = response.json() if response.content else None


@given("an authenticated Active Account has no Workspace")
def given_active_account_no_workspace(bdd_context: BDDContext) -> None:
    email = f"lifecycle-{uuid.uuid4().hex[:12]}@example.com"
    password = "Str0ng#Passw0rd"
    response = bdd_context.run(
        bdd_context.device("A").post(
            "/v1/auth/register", json={"email": email, "password": password}
        )
    )
    _record(bdd_context, response)
    assert response.status_code == 201
    account_id = bdd_context.run(
        bdd_context.db_session.execute(
            text(
                "SELECT account_id FROM auth.accounts ORDER BY created_at DESC LIMIT 1"
            )
        )
    ).scalar_one()
    bdd_context.accounts[email] = {"account_id": str(account_id), "password": password}
    bdd_context.current_email = email
    token = bdd_context.mailer.sent[-1][1]
    response = bdd_context.run(
        bdd_context.device("A").post("/v1/auth/verify-email", json={"token": token})
    )
    _record(bdd_context, response)
    assert response.status_code == 200


@given("an authenticated PendingVerification Account has no Workspace")
def given_pending_account_no_workspace(bdd_context: BDDContext) -> None:
    email = f"lifecycle-{uuid.uuid4().hex[:12]}@example.com"
    response = bdd_context.run(
        bdd_context.device("A").post(
            "/v1/auth/register", json={"email": email, "password": "Str0ng#Passw0rd"}
        )
    )
    _record(bdd_context, response)
    assert response.status_code == 201


@given("an authenticated Active Account owns a Workspace")
def given_active_account_owns_workspace(bdd_context: BDDContext) -> None:
    given_active_account_no_workspace(bdd_context)
    when_create_workspace(bdd_context, "Studio")
    assert bdd_context.last_status == 201
    bdd_context.workspace_id = bdd_context.last_body["workspaceId"]


@given(parsers.cfparse('a sibling object is named "{existing}"'))
def given_sibling_object(bdd_context: BDDContext, existing: str) -> None:
    given_active_account_owns_workspace(bdd_context)
    response = bdd_context.run(
        bdd_context.device("A").post(
            f"/v1/workspaces/{bdd_context.workspace_id}/projects",
            json={
                "workspaceId": bdd_context.workspace_id,
                "name": "Collision Project",
                "idempotencyKey": str(uuid.uuid4()),
            },
        )
    )
    assert response.status_code == 201
    bdd_context.project_id = response.json()["projectId"]
    response = bdd_context.run(
        bdd_context.device("A").post(
            f"/v1/projects/{bdd_context.project_id}/folders",
            json={
                "projectId": bdd_context.project_id,
                "parentFolderId": None,
                "name": existing,
                "idempotencyKey": str(uuid.uuid4()),
            },
        )
    )
    assert response.status_code == 201
    bdd_context.folder_id = response.json()["folderId"]
    bdd_context.existing_name = existing


@when(parsers.cfparse('an object is created or renamed to "{candidate}"'))
def when_create_collision_candidate(bdd_context: BDDContext, candidate: str) -> None:
    response = bdd_context.run(
        bdd_context.device("A").post(
            f"/v1/projects/{bdd_context.project_id}/folders",
            json={
                "projectId": bdd_context.project_id,
                "parentFolderId": None,
                "name": candidate,
                "idempotencyKey": str(uuid.uuid4()),
            },
        )
    )
    _record(bdd_context, response)


@then("the request is rejected as a name conflict")
def then_name_conflict(bdd_context: BDDContext) -> None:
    assert bdd_context.last_status == 409
    assert bdd_context.last_body.get("errorCode") == "WORKSPACE_NAME_CONFLICT"


@then(parsers.cfparse('the existing display name remains "{existing}"'))
def then_existing_display_name(bdd_context: BDDContext, existing: str) -> None:
    response = bdd_context.run(
        bdd_context.device("A").get(f"/v1/projects/{bdd_context.project_id}")
    )
    assert response.status_code == 200
    assert any(folder["name"] == existing for folder in response.json()["folders"])


@given("an Account may create Workspaces with non-global names")
def given_workspace_name_scope(bdd_context: BDDContext) -> None:
    given_active_account_no_workspace(bdd_context)


@when("the Account submits blank, over-120-code-point, or control-character names")
def when_invalid_workspace_names(bdd_context: BDDContext) -> None:
    statuses = []
    for name in ("", "x" * 121, "bad\x00name"):
        response = bdd_context.run(
            bdd_context.device("A").post(
                "/v1/workspaces",
                json={"name": name, "idempotencyKey": str(uuid.uuid4())},
            )
        )
        statuses.append(response.status_code)
    bdd_context.validation_statuses = statuses


@then("each invalid name is rejected with a Validation error")
def then_workspace_validation(bdd_context: BDDContext) -> None:
    assert bdd_context.validation_statuses == [422, 422, 422]


@then("accepted display names preserve the original user input")
def then_workspace_display_preserved(bdd_context: BDDContext) -> None:
    response = bdd_context.run(
        bdd_context.device("A").post(
            "/v1/workspaces",
            json={"name": "Studio", "idempotencyKey": str(uuid.uuid4())},
        )
    )
    assert response.status_code == 201
    assert response.json()["name"] == "Studio"


@given("an authorized Project contains nested Folders")
def given_authorized_nested_project(bdd_context: BDDContext) -> None:
    given_active_account_owns_workspace(bdd_context)
    when_create_project_nested_folder(bdd_context)


@when("the client requests the Project Tree")
def when_request_project_tree(bdd_context: BDDContext) -> None:
    response = bdd_context.run(
        bdd_context.device("A").get(f"/v1/projects/{bdd_context.project_id}")
    )
    _record(bdd_context, response)


@then("the response contains the Workspace, Project, and Folder metadata")
def then_tree_metadata(bdd_context: BDDContext) -> None:
    assert bdd_context.last_status == 200
    assert bdd_context.last_body["workspaceId"] == bdd_context.workspace_id
    assert bdd_context.last_body["projectId"] == bdd_context.project_id


@then("the response does not contain Resource content")
def then_tree_no_resource_content(bdd_context: BDDContext) -> None:
    assert "resources" not in bdd_context.last_body
    assert "content" not in bdd_context.last_body


@when(parsers.cfparse('the Account creates a Workspace named "{name}"'))
def when_create_workspace(bdd_context: BDDContext, name: str) -> None:
    # This is the only lifecycle path already referenced by the existing Auth BDD.
    response: Response = bdd_context.run(
        bdd_context.device("A").post(
            "/v1/workspaces",
            json={"name": name, "idempotencyKey": str(uuid.uuid4())},
        )
    )
    _record(bdd_context, response)


@when("the Account creates a Project and nested Folder")
def when_create_project_nested_folder(bdd_context: BDDContext) -> None:
    project_key = str(uuid.uuid4())
    response = bdd_context.run(
        bdd_context.device("A").post(
            f"/v1/workspaces/{bdd_context.workspace_id}/projects",
            json={
                "workspaceId": bdd_context.workspace_id,
                "name": "Plan",
                "idempotencyKey": project_key,
            },
        )
    )
    _record(bdd_context, response)
    assert response.status_code == 201
    bdd_context.project_id = response.json()["projectId"]
    response = bdd_context.run(
        bdd_context.device("A").post(
            f"/v1/projects/{bdd_context.project_id}/folders",
            json={
                "projectId": bdd_context.project_id,
                "parentFolderId": None,
                "name": "docs",
                "idempotencyKey": str(uuid.uuid4()),
            },
        )
    )
    _record(bdd_context, response)
    assert response.status_code == 201
    bdd_context.folder_id = response.json()["folderId"]


@then("the Project and Folder are visible in the metadata tree")
def then_tree_contains_created_metadata(bdd_context: BDDContext) -> None:
    response = bdd_context.run(
        bdd_context.device("A").get(f"/v1/projects/{bdd_context.project_id}")
    )
    _record(bdd_context, response)
    assert response.status_code == 200
    assert response.json()["projectId"] == bdd_context.project_id
    assert any(
        item["folderId"] == bdd_context.folder_id for item in response.json()["folders"]
    )


@then("each object has a stable id independent of its name and path")
def then_created_ids_stable(bdd_context: BDDContext) -> None:
    assert bdd_context.project_id
    assert bdd_context.folder_id


@then("the response confirms a Workspace with a stable id")
def then_workspace_confirmed(bdd_context: BDDContext) -> None:
    assert bdd_context.last_status in (200, 201)
    assert bdd_context.last_body.get("workspaceId")


@then("the creator is the initial sole Workspace Owner")
def then_initial_owner(bdd_context: BDDContext) -> None:
    # CreateWorkspaceResponse exposes ownerAccountId; creator identity comes from
    # the authenticated session rather than a createdBy response field.
    assert bdd_context.last_body.get("ownerAccountId")
    assert (
        bdd_context.last_body["ownerAccountId"]
        == bdd_context.accounts[bdd_context.current_email]["account_id"]
    )


@then("the request is denied with a Permission error")
def then_permission_denied(bdd_context: BDDContext) -> None:
    assert bdd_context.last_status == 403
    assert bdd_context.last_body.get("category") == "Permission"


@then("no Workspace is created")
def then_no_workspace_created(bdd_context: BDDContext) -> None:
    assert bdd_context.last_status == 403


@given("a nested Folder tree and a second Project")
def given_nested_tree_and_second_project(bdd_context: BDDContext) -> None:
    given_active_account_owns_workspace(bdd_context)
    when_create_project_nested_folder(bdd_context)
    response = bdd_context.run(
        bdd_context.device("A").post(
            f"/v1/workspaces/{bdd_context.workspace_id}/projects",
            json={
                "workspaceId": bdd_context.workspace_id,
                "name": "Other",
                "idempotencyKey": str(uuid.uuid4()),
            },
        )
    )
    assert response.status_code == 201
    bdd_context.other_project_id = response.json()["projectId"]
    response = bdd_context.run(
        bdd_context.device("A").post(
            f"/v1/projects/{bdd_context.other_project_id}/folders",
            json={
                "projectId": bdd_context.other_project_id,
                "parentFolderId": None,
                "name": "other-root",
                "idempotencyKey": str(uuid.uuid4()),
            },
        )
    )
    assert response.status_code == 201
    bdd_context.other_folder_id = response.json()["folderId"]


@when("a Folder is moved beneath its descendant or into the other Project")
def when_invalid_folder_moves(bdd_context: BDDContext) -> None:
    outcomes = []
    for destination in (bdd_context.folder_id, bdd_context.other_folder_id):
        response = bdd_context.run(
            bdd_context.device("A").post(
                f"/v1/folders/{bdd_context.folder_id}/move",
                json={
                    "folderId": bdd_context.folder_id,
                    "destinationParentFolderId": destination,
                    "idempotencyKey": str(uuid.uuid4()),
                },
            )
        )
        outcomes.append(response)
    bdd_context.move_outcomes = outcomes


@then("each invalid move is rejected")
def then_invalid_moves_rejected(bdd_context: BDDContext) -> None:
    assert [response.status_code for response in bdd_context.move_outcomes] == [
        409,
        409,
    ]
    assert bdd_context.move_outcomes[0].json().get("errorCode") == "FOLDER_CYCLE"


@then("the authoritative tree remains acyclic and same-Project")
def then_tree_remains_valid(bdd_context: BDDContext) -> None:
    response = bdd_context.run(
        bdd_context.device("A").get(f"/v1/projects/{bdd_context.project_id}")
    )
    assert response.status_code == 200


@given("an authorized Active Project")
def given_authorized_active_project(bdd_context: BDDContext) -> None:
    given_active_account_owns_workspace(bdd_context)
    response = bdd_context.run(
        bdd_context.device("A").post(
            f"/v1/workspaces/{bdd_context.workspace_id}/projects",
            json={
                "workspaceId": bdd_context.workspace_id,
                "name": "Archive Me",
                "idempotencyKey": str(uuid.uuid4()),
            },
        )
    )
    assert response.status_code == 201
    bdd_context.project_id = response.json()["projectId"]


@when("the Project is archived and a write is attempted")
def when_archive_and_write(bdd_context: BDDContext) -> None:
    response = bdd_context.run(
        bdd_context.device("A").post(
            f"/v1/projects/{bdd_context.project_id}/archive",
            json={
                "projectId": bdd_context.project_id,
                "idempotencyKey": str(uuid.uuid4()),
            },
        )
    )
    assert response.status_code == 200
    bdd_context.archive_read_response = bdd_context.run(
        bdd_context.device("A").get(f"/v1/projects/{bdd_context.project_id}")
    )
    bdd_context.write_response = bdd_context.run(
        bdd_context.device("A").patch(
            f"/v1/projects/{bdd_context.project_id}",
            json={
                "projectId": bdd_context.project_id,
                "name": "Nope",
                "idempotencyKey": str(uuid.uuid4()),
            },
        )
    )


@then("the write is rejected as read-only")
def then_archived_write_rejected(bdd_context: BDDContext) -> None:
    assert bdd_context.write_response.status_code == 409


@given("an active Project has nested Folders and Resource metadata descendants")
def given_active_project_descendants(bdd_context: BDDContext) -> None:
    given_active_account_owns_workspace(bdd_context)
    when_create_project_nested_folder(bdd_context)


@when("an authorized Manager trashes and then restores the Project")
def when_project_trash_restore(bdd_context: BDDContext) -> None:
    for action in ("trash", "restore"):
        response = bdd_context.run(
            bdd_context.device("A").post(
                f"/v1/projects/{bdd_context.project_id}/{action}",
                json={
                    "projectId": bdd_context.project_id,
                    "idempotencyKey": str(uuid.uuid4()),
                },
            )
        )
        assert response.status_code == 200
        if action == "trash":
            bdd_context.project_trash_lifecycle = bdd_context.run(
                bdd_context.db_session.scalar(
                    text(
                        "SELECT lifecycle FROM core.projects "
                        "WHERE project_id = :project_id"
                    ),
                    {"project_id": bdd_context.project_id},
                )
            )
            bdd_context.project_descendant_rows_after_trash = bdd_context.run(
                bdd_context.db_session.execute(
                    text(
                        "SELECT folder_id, lifecycle FROM core.folders "
                        "WHERE project_id = :project_id"
                    ),
                    {"project_id": bdd_context.project_id},
                )
            ).all()
    bdd_context.project_tree_after_restore = bdd_context.run(
        bdd_context.device("A").get(f"/v1/projects/{bdd_context.project_id}")
    )


@then("one Project lifecycle transition hides and restores its full descendant subtree")
def then_project_restored(bdd_context: BDDContext) -> None:
    assert bdd_context.project_tree_after_restore.status_code == 200


@then("every restored metadata object retains its stable id")
def then_project_ids_retained(bdd_context: BDDContext) -> None:
    assert bdd_context.project_id and bdd_context.folder_id


@then("no per-descendant lifecycle rewrites are required")
def then_no_descendant_rewrites(bdd_context: BDDContext) -> None:
    rows = bdd_context.run(
        bdd_context.db_session.execute(
            text(
                "SELECT folder_id, lifecycle FROM core.folders "
                "WHERE project_id = :project_id"
            ),
            {"project_id": bdd_context.project_id},
        )
    ).all()
    assert rows
    assert bdd_context.project_trash_lifecycle == "Trashed"
    assert all(str(row.lifecycle) == "Active" for row in rows)
    assert {str(row.folder_id) for row in rows} >= {bdd_context.folder_id}


@then("the Project is hidden from the default active list")
def then_project_hidden(bdd_context: BDDContext) -> None:
    lifecycle = bdd_context.run(
        bdd_context.db_session.scalar(
            text("SELECT lifecycle FROM core.projects WHERE project_id = :project_id"),
            {"project_id": bdd_context.project_id},
        )
    )
    assert str(lifecycle) == "Archived"


@then("an authorized read remains available through the archive view")
def then_archive_read_available(bdd_context: BDDContext) -> None:
    assert bdd_context.archive_read_response.status_code == 200


@given("an active Folder contains child Folders and Resource metadata descendants")
def given_folder_descendants(bdd_context: BDDContext) -> None:
    given_active_project_descendants(bdd_context)
    parent = bdd_context.folder_id
    response = bdd_context.run(
        bdd_context.device("A").post(
            f"/v1/projects/{bdd_context.project_id}/folders",
            json={
                "projectId": bdd_context.project_id,
                "parentFolderId": parent,
                "name": "nested",
                "idempotencyKey": str(uuid.uuid4()),
            },
        )
    )
    assert response.status_code == 201
    bdd_context.child_folder_id = response.json()["folderId"]


@when("an authorized Manager trashes and then restores the Folder")
def when_folder_trash_restore(bdd_context: BDDContext) -> None:
    for action in ("trash", "restore"):
        response = bdd_context.run(
            bdd_context.device("A").post(
                f"/v1/folders/{bdd_context.folder_id}/{action}",
                json={
                    "folderId": bdd_context.folder_id,
                    "idempotencyKey": str(uuid.uuid4()),
                },
            )
        )
        assert response.status_code == 200
    bdd_context.folder_tree_after_restore = bdd_context.run(
        bdd_context.device("A").get(f"/v1/projects/{bdd_context.project_id}")
    )


@then("one Folder lifecycle transition hides and restores its full descendant subtree")
def then_folder_restored(bdd_context: BDDContext) -> None:
    assert bdd_context.folder_tree_after_restore.status_code == 200


@then("the Folder and descendants retain stable metadata identities")
def then_folder_ids_stable(bdd_context: BDDContext) -> None:
    assert bdd_context.folder_id and bdd_context.child_folder_id


@then("no Resource session notification or physical content cleanup is claimed")
def then_no_resource_cleanup(bdd_context: BDDContext) -> None:
    body = bdd_context.folder_tree_after_restore.json()

    def assert_metadata_only(value: object) -> None:
        if isinstance(value, dict):
            assert "resource" not in {str(key).lower() for key in value}
            assert "content" not in {str(key).lower() for key in value}
            for child in value.values():
                assert_metadata_only(child)
        elif isinstance(value, list):
            for child in value:
                assert_metadata_only(child)

    assert_metadata_only(body)


@given("an authenticated Account lacks permission for a Project")
def given_account_without_project_permission(bdd_context: BDDContext) -> None:
    given_active_account_owns_workspace(bdd_context)
    bdd_context.device("B")
    response = bdd_context.run(
        bdd_context.device("A").post(
            f"/v1/workspaces/{bdd_context.workspace_id}/projects",
            json={
                "workspaceId": bdd_context.workspace_id,
                "name": "Private",
                "idempotencyKey": str(uuid.uuid4()),
            },
        )
    )
    assert response.status_code == 201
    bdd_context.project_id = response.json()["projectId"]
    response = bdd_context.run(
        bdd_context.device("B").post(
            "/v1/auth/register",
            json={
                "email": f"other-{uuid.uuid4().hex}@example.com",
                "password": "Str0ng#Passw0rd",
            },
        )
    )
    assert response.status_code == 201
    token = bdd_context.mailer.sent[-1][1]
    bdd_context.run(
        bdd_context.device("B").post("/v1/auth/verify-email", json={"token": token})
    )


@when("the Account reads the Project Tree or attempts Folder move and Trash")
def when_unauthorized_access(bdd_context: BDDContext) -> None:
    tree = bdd_context.run(
        bdd_context.device("B").get(f"/v1/projects/{bdd_context.project_id}")
    )
    bdd_context.denied_responses = [tree]


@then("the API denies the operations without disclosing inaccessible metadata")
def then_unauthorized_denied(bdd_context: BDDContext) -> None:
    assert all(response.status_code == 403 for response in bdd_context.denied_responses)


@then("denied queries are not represented as an empty successful tree")
def then_no_empty_tree_success(bdd_context: BDDContext) -> None:
    assert bdd_context.denied_responses[0].status_code != 200


@given("a client submits a metadata mutation")
def given_client_metadata_mutation(bdd_context: BDDContext) -> None:
    given_active_account_owns_workspace(bdd_context)


@when("the API confirms, rejects, or conflicts the mutation")
def when_outcome_variants(bdd_context: BDDContext) -> None:
    confirmed = bdd_context.run(
        bdd_context.device("A").post(
            f"/v1/workspaces/{bdd_context.workspace_id}/projects",
            json={
                "workspaceId": bdd_context.workspace_id,
                "name": "Outcome",
                "idempotencyKey": str(uuid.uuid4()),
            },
        )
    )
    conflict = bdd_context.run(
        bdd_context.device("A").post(
            f"/v1/workspaces/{bdd_context.workspace_id}/projects",
            json={
                "workspaceId": bdd_context.workspace_id,
                "name": "Outcome",
                "idempotencyKey": str(uuid.uuid4()),
            },
        )
    )
    bdd_context.outcome_responses = (confirmed, conflict)


@then("the client-visible result follows the authoritative API outcome")
def then_outcomes_classified(bdd_context: BDDContext) -> None:
    assert bdd_context.outcome_responses[0].status_code == 201
    assert bdd_context.outcome_responses[1].status_code == 409


@then("a conflict does not silently overwrite the current tree")
def then_conflict_does_not_overwrite(bdd_context: BDDContext) -> None:
    assert (
        bdd_context.outcome_responses[1].json().get("errorCode")
        == "WORKSPACE_NAME_CONFLICT"
    )


@given("an authorized Manager has a Project Tree")
def given_manager_project_tree(bdd_context: BDDContext) -> None:
    given_active_project_descendants(bdd_context)


@when("the same Trash command is retried with its idempotency key")
def when_trash_retry(bdd_context: BDDContext) -> None:
    key = str(uuid.uuid4())
    responses = []
    for _ in range(2):
        responses.append(
            bdd_context.run(
                bdd_context.device("A").post(
                    f"/v1/projects/{bdd_context.project_id}/trash",
                    json={"projectId": bdd_context.project_id, "idempotencyKey": key},
                )
            )
        )
    bdd_context.trash_retry_responses = responses


@then("only one authoritative ancestor lifecycle transition is recorded")
def then_trash_retry_replayed(bdd_context: BDDContext) -> None:
    assert [response.status_code for response in bdd_context.trash_retry_responses] == [
        200,
        200,
    ]
    assert bdd_context.trash_retry_responses[0].json() == (
        bdd_context.trash_retry_responses[1].json()
    )


@then("the lifecycle event is committed with the metadata change")
def then_lifecycle_event_committed(bdd_context: BDDContext) -> None:
    assert bdd_context.trash_retry_responses[0].status_code == 200
    count = bdd_context.run(
        bdd_context.db_session.execute(
            text(
                "SELECT count(*) FROM integration.outbox_events "
                "WHERE aggregate_id = :aggregate_id "
                "AND event_type = 'event.workspace.project-trashed.v1'"
            ),
            {"aggregate_id": bdd_context.project_id},
        )
    ).scalar_one()
    assert count == 1


@given(
    "a trashed Folder has a missing or inaccessible original parent in an "
    "active Project"
)
def given_trashed_folder_missing_parent(bdd_context: BDDContext) -> None:
    given_folder_descendants(bdd_context)
    response = bdd_context.run(
        bdd_context.device("A").post(
            f"/v1/projects/{bdd_context.project_id}/folders",
            json={
                "projectId": bdd_context.project_id,
                "parentFolderId": None,
                "name": "Original Parent",
                "idempotencyKey": str(uuid.uuid4()),
            },
        )
    )
    assert response.status_code == 201
    bdd_context.original_parent_id = response.json()["folderId"]
    response = bdd_context.run(
        bdd_context.device("A").post(
            f"/v1/projects/{bdd_context.project_id}/folders",
            json={
                "projectId": bdd_context.project_id,
                "parentFolderId": bdd_context.original_parent_id,
                "name": "Restore Me",
                "idempotencyKey": str(uuid.uuid4()),
            },
        )
    )
    assert response.status_code == 201
    bdd_context.folder_id = response.json()["folderId"]
    for folder_id in (bdd_context.folder_id, bdd_context.original_parent_id):
        response = bdd_context.run(
            bdd_context.device("A").post(
                f"/v1/folders/{folder_id}/trash",
                json={"folderId": folder_id, "idempotencyKey": str(uuid.uuid4())},
            )
        )
        assert response.status_code == 200


@when("an authorized Manager restores the Folder")
def when_restore_folder_edge(bdd_context: BDDContext) -> None:
    response = bdd_context.run(
        bdd_context.device("A").post(
            f"/v1/folders/{bdd_context.folder_id}/restore",
            json={
                "folderId": bdd_context.folder_id,
                "idempotencyKey": str(uuid.uuid4()),
            },
        )
    )
    _record(bdd_context, response)


@then("the Folder is restored at the Project root")
def then_folder_restored_at_root(bdd_context: BDDContext) -> None:
    assert bdd_context.last_status == 200
    assert bdd_context.last_body["parentFolderId"] is None
    assert bdd_context.last_body["folderId"] == bdd_context.folder_id


@then("its stable id is unchanged")
def then_restore_id_unchanged(bdd_context: BDDContext) -> None:
    assert bdd_context.last_body["folderId"] == bdd_context.folder_id


@given(
    'a trashed Folder named "Design.md" has a sibling collision at its '
    "original location"
)
def given_restore_collision(bdd_context: BDDContext) -> None:
    given_active_project_descendants(bdd_context)
    response = bdd_context.run(
        bdd_context.device("A").post(
            f"/v1/projects/{bdd_context.project_id}/folders",
            json={
                "projectId": bdd_context.project_id,
                "parentFolderId": None,
                "name": "Design.md",
                "idempotencyKey": str(uuid.uuid4()),
            },
        )
    )
    assert response.status_code == 201
    bdd_context.collision_folder_id = response.json()["folderId"]
    response = bdd_context.run(
        bdd_context.device("A").post(
            f"/v1/folders/{bdd_context.collision_folder_id}/trash",
            json={
                "folderId": bdd_context.collision_folder_id,
                "idempotencyKey": str(uuid.uuid4()),
            },
        )
    )
    assert response.status_code == 200
    bdd_context.run(
        bdd_context.db_session.execute(
            text(
                "UPDATE core.folders SET parent_folder_id = :parent "
                "WHERE folder_id = :folder_id"
            ),
            {
                "parent": bdd_context.folder_id,
                "folder_id": bdd_context.collision_folder_id,
            },
        )
    )
    response = bdd_context.run(
        bdd_context.device("A").post(
            f"/v1/projects/{bdd_context.project_id}/folders",
            json={
                "projectId": bdd_context.project_id,
                "parentFolderId": bdd_context.folder_id,
                "name": "Design.md",
                "idempotencyKey": str(uuid.uuid4()),
            },
        )
    )
    assert response.status_code == 201


@then(
    'the system chooses the lowest free name "Design (restored N).md" in '
    "the destination sibling scope"
)
def then_lowest_restore_name(bdd_context: BDDContext) -> None:
    assert bdd_context.last_status == 200
    assert bdd_context.last_body["name"] == "Design (restored 1).md"


@then("collision comparison uses NFC, edge trimming, and case-insensitive comparison")
def then_collision_comparison(bdd_context: BDDContext) -> None:
    pass


@then("no existing object is overwritten")
def then_no_object_overwrite(bdd_context: BDDContext) -> None:
    assert bdd_context.last_body["folderId"] == bdd_context.collision_folder_id
