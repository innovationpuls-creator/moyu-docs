from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import UUID

import pytest
from api.dependencies.auth import get_current_session
from api.dependencies.workspace import (
    get_create_folder_use_case,
    get_create_project_use_case,
    get_create_workspace_use_case,
    get_folder_lifecycle_use_cases,
    get_get_project_tree_use_case,
    get_move_folder_use_case,
    get_project_lifecycle_use_cases,
    get_rename_project_use_case,
    get_transfer_workspace_owner_use_case,
    get_workspace_use_case,
)
from api.main import create_app
from api.middleware.recovery_mode_guard import get_recovery_guard
from app_core.workspace.domain.folder import FolderExtendedLifecycle
from app_core.workspace.domain.lifecycle import WorkspaceLifecycle
from app_core.workspace.domain.name import WorkspaceName
from app_core.workspace.domain.project import ProjectExtendedLifecycle
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

ACTOR_ID = UUID("10000000-0000-0000-0000-000000000001")
WORKSPACE_ID = UUID("20000000-0000-0000-0000-000000000002")
IDEMPOTENCY_KEY = UUID("30000000-0000-0000-0000-000000000003")
CREATED_AT = datetime(2026, 9, 24, 12, 0, tzinfo=UTC)


class _CreateWorkspace:
    def __init__(self) -> None:
        self.calls: list[tuple[UUID, str, str]] = []

    async def execute(
        self, actor_id: UUID, name: str, *, idempotency_key: str
    ) -> SimpleNamespace:
        self.calls.append((actor_id, name, idempotency_key))
        return SimpleNamespace(
            workspace=SimpleNamespace(
                workspace_id=WORKSPACE_ID,
                name=WorkspaceName(name),
                created_at=CREATED_AT,
            ),
            owner_account_id=ACTOR_ID,
        )


class _TransferWorkspace:
    def __init__(self) -> None:
        self.calls: list[tuple[UUID, UUID, UUID, str]] = []

    async def execute(
        self,
        actor_id: UUID,
        workspace_id: UUID,
        new_owner_id: UUID,
        idempotency_key: str,
    ) -> SimpleNamespace:
        self.calls.append((actor_id, workspace_id, new_owner_id, idempotency_key))
        return SimpleNamespace(
            workspace_id=workspace_id,
            previous_owner_account_id=actor_id,
            new_owner_account_id=new_owner_id,
            previous_owner_remains_member=True,
            independent_project_owner_rows_changed=False,
            transferred_at=CREATED_AT,
        )


class _GetWorkspace:
    def __init__(self) -> None:
        self.calls: list[tuple[UUID, UUID]] = []

    async def execute(self, actor_id: UUID, workspace_id: UUID) -> SimpleNamespace:
        self.calls.append((actor_id, workspace_id))
        return SimpleNamespace(
            workspace=SimpleNamespace(
                workspace_id=WORKSPACE_ID,
                name=WorkspaceName("Roadmap"),
                lifecycle=WorkspaceLifecycle.ACTIVE,
                created_at=CREATED_AT,
                updated_at=CREATED_AT,
            ),
            owner_account_id=ACTOR_ID,
        )


@pytest.mark.asyncio
async def test_create_workspace_uses_session_actor_and_generated_response() -> None:
    use_case = _CreateWorkspace()
    app: FastAPI = create_app(debug=True)
    app.dependency_overrides[get_current_session] = lambda: SimpleNamespace(
        account_id=ACTOR_ID
    )
    app.dependency_overrides[get_recovery_guard] = lambda: None
    app.dependency_overrides[get_create_workspace_use_case] = lambda: use_case

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post(
            "/v1/workspaces",
            json={"name": "Roadmap", "idempotencyKey": str(IDEMPOTENCY_KEY)},
        )

    assert response.status_code == 201
    assert response.json() == {
        "workspaceId": str(WORKSPACE_ID),
        "name": "Roadmap",
        "ownerAccountId": str(ACTOR_ID),
        "createdAt": CREATED_AT.isoformat().replace("+00:00", "Z"),
    }
    assert use_case.calls == [(ACTOR_ID, "Roadmap", str(IDEMPOTENCY_KEY))]


@pytest.mark.asyncio
async def test_get_workspace_returns_permission_owned_owner_projection() -> None:
    use_case = _GetWorkspace()
    app: FastAPI = create_app(debug=True)
    app.dependency_overrides[get_current_session] = lambda: SimpleNamespace(
        account_id=ACTOR_ID
    )
    app.dependency_overrides[get_recovery_guard] = lambda: None
    app.dependency_overrides[get_workspace_use_case] = lambda: use_case

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get(f"/v1/workspaces/{WORKSPACE_ID}")

    assert response.status_code == 200
    assert response.json() == {
        "workspaceId": str(WORKSPACE_ID),
        "name": "Roadmap",
        "ownerAccountId": str(ACTOR_ID),
        "lifecycle": "Active",
        "createdAt": CREATED_AT.isoformat().replace("+00:00", "Z"),
        "updatedAt": CREATED_AT.isoformat().replace("+00:00", "Z"),
    }
    assert use_case.calls == [(ACTOR_ID, WORKSPACE_ID)]


@pytest.mark.asyncio
async def test_transfer_owner_uses_trusted_actor_and_request_identity() -> None:
    use_case = _TransferWorkspace()
    app: FastAPI = create_app(debug=True)
    app.dependency_overrides[get_current_session] = lambda: SimpleNamespace(
        account_id=ACTOR_ID
    )
    app.dependency_overrides[get_recovery_guard] = lambda: None
    app.dependency_overrides[get_transfer_workspace_owner_use_case] = lambda: use_case
    new_owner_id = UUID("40000000-0000-0000-0000-000000000004")

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post(
            f"/v1/workspaces/{WORKSPACE_ID}/owner",
            headers={"Idempotency-Key": str(IDEMPOTENCY_KEY)},
            json={
                "workspaceId": str(WORKSPACE_ID),
                "newOwnerAccountId": str(new_owner_id),
                "idempotencyKey": str(IDEMPOTENCY_KEY),
            },
        )

    assert response.status_code == 200
    assert response.json() == {
        "workspaceId": str(WORKSPACE_ID),
        "previousOwnerAccountId": str(ACTOR_ID),
        "newOwnerAccountId": str(new_owner_id),
        "previousOwnerRemainsMember": True,
        "independentProjectOwnerRowsChanged": False,
        "transferredAt": CREATED_AT.isoformat().replace("+00:00", "Z"),
    }
    assert use_case.calls == [
        (ACTOR_ID, WORKSPACE_ID, new_owner_id, str(IDEMPOTENCY_KEY))
    ]


@pytest.mark.asyncio
async def test_transfer_owner_rejects_mismatched_header_idempotency_key() -> None:
    app: FastAPI = create_app(debug=True)
    app.dependency_overrides[get_current_session] = lambda: SimpleNamespace(
        account_id=ACTOR_ID
    )
    app.dependency_overrides[get_recovery_guard] = lambda: None
    app.dependency_overrides[get_transfer_workspace_owner_use_case] = lambda: (
        _TransferWorkspace()
    )
    different_key = UUID("50000000-0000-0000-0000-000000000005")

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post(
            f"/v1/workspaces/{WORKSPACE_ID}/owner",
            headers={"Idempotency-Key": str(different_key)},
            json={
                "workspaceId": str(WORKSPACE_ID),
                "newOwnerAccountId": str(UUID("40000000-0000-0000-0000-000000000004")),
                "idempotencyKey": str(IDEMPOTENCY_KEY),
            },
        )

    assert response.status_code == 409
    assert response.json()["errorCode"] == "IDEMPOTENCY_KEY_CONFLICT"


@pytest.mark.asyncio
class _CreateProject:
    def __init__(self) -> None:
        self.calls: list[tuple] = []

    async def execute(self, actor_id, workspace_id, name, *, idempotency_key):
        self.calls.append((actor_id, workspace_id, name, idempotency_key))
        return SimpleNamespace(
            project_id=UUID("60000000-0000-0000-0000-000000000006"),
            workspace_id=workspace_id,
            name=WorkspaceName(name),
            created_at=CREATED_AT,
        )


class _CreateFolder:
    def __init__(self) -> None:
        self.calls: list[tuple] = []

    async def execute(
        self, actor_id, project_id, parent_folder_id, name, *, idempotency_key
    ):
        self.calls.append(
            (actor_id, project_id, parent_folder_id, name, idempotency_key)
        )
        return SimpleNamespace(
            folder_id=UUID("70000000-0000-0000-0000-000000000007"),
            project_id=project_id,
            parent_folder_id=parent_folder_id,
            name=WorkspaceName(name),
            created_at=CREATED_AT,
        )


class _MoveFolder:
    def __init__(self) -> None:
        self.calls: list[tuple] = []

    async def execute(
        self, actor_id, folder_id, destination_parent_folder_id, *, idempotency_key
    ):
        self.calls.append(
            (actor_id, folder_id, destination_parent_folder_id, idempotency_key)
        )
        return SimpleNamespace(
            folder_id=folder_id,
            project_id=PROJECT_ID,
            parent_folder_id=destination_parent_folder_id,
            updated_at=CREATED_AT,
        )


class _GetProjectTree:
    async def execute(self, actor_id, project_id):
        return SimpleNamespace(
            workspace_id=WORKSPACE_ID,
            project=SimpleNamespace(
                project_id=PROJECT_ID,
                name=WorkspaceName("Plan"),
                lifecycle=ProjectExtendedLifecycle.ACTIVE,
            ),
            folders=(
                SimpleNamespace(
                    folder_id=FOLDER_ID,
                    parent_folder_id=None,
                    name=WorkspaceName("docs"),
                    lifecycle=FolderExtendedLifecycle.ACTIVE,
                    has_children=False,
                ),
            ),
            next_cursor=None,
        )


PROJECT_ID = UUID("60000000-0000-0000-0000-000000000006")
FOLDER_ID = UUID("70000000-0000-0000-0000-000000000007")


@pytest.mark.asyncio
async def test_create_project_maps_request_actor_and_response() -> None:
    use_case = _CreateProject()
    app: FastAPI = create_app(debug=True)
    app.dependency_overrides[get_current_session] = lambda: SimpleNamespace(
        account_id=ACTOR_ID
    )
    app.dependency_overrides[get_recovery_guard] = lambda: None
    app.dependency_overrides[get_create_project_use_case] = lambda: use_case

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post(
            "/v1/workspaces/" + str(WORKSPACE_ID) + "/projects",
            json={
                "workspaceId": str(WORKSPACE_ID),
                "name": "Plan",
                "idempotencyKey": str(IDEMPOTENCY_KEY),
            },
        )

    assert response.status_code == 201
    assert response.json()["projectId"] == str(PROJECT_ID)
    assert use_case.calls == [(ACTOR_ID, WORKSPACE_ID, "Plan", str(IDEMPOTENCY_KEY))]


@pytest.mark.asyncio
async def test_create_folder_maps_request_actor_and_response() -> None:
    use_case = _CreateFolder()
    app: FastAPI = create_app(debug=True)
    app.dependency_overrides[get_current_session] = lambda: SimpleNamespace(
        account_id=ACTOR_ID
    )
    app.dependency_overrides[get_recovery_guard] = lambda: None
    app.dependency_overrides[get_create_folder_use_case] = lambda: use_case

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post(
            "/v1/projects/" + str(PROJECT_ID) + "/folders",
            json={
                "projectId": str(PROJECT_ID),
                "parentFolderId": None,
                "name": "docs",
                "idempotencyKey": str(IDEMPOTENCY_KEY),
            },
        )

    assert response.status_code == 201
    assert response.json()["folderId"] == str(FOLDER_ID)
    assert use_case.calls == [
        (ACTOR_ID, PROJECT_ID, None, "docs", str(IDEMPOTENCY_KEY))
    ]


@pytest.mark.asyncio
async def test_move_folder_conflict_propagates_error_envelope() -> None:
    class ConflictMove(_MoveFolder):
        async def execute(self, *args, **kwargs):
            from app_core.common.exceptions import ConflictError

            raise ConflictError("cycle", "FOLDER_CYCLE")

    app: FastAPI = create_app(debug=True)
    app.dependency_overrides[get_current_session] = lambda: SimpleNamespace(
        account_id=ACTOR_ID
    )
    app.dependency_overrides[get_recovery_guard] = lambda: None
    app.dependency_overrides[get_move_folder_use_case] = lambda: ConflictMove()

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post(
            "/v1/folders/" + str(FOLDER_ID) + "/move",
            json={
                "folderId": str(FOLDER_ID),
                "destinationParentFolderId": None,
                "idempotencyKey": str(IDEMPOTENCY_KEY),
            },
        )

    assert response.status_code == 409
    assert response.json()["errorCode"] == "FOLDER_CYCLE"


@pytest.mark.asyncio
async def test_get_project_tree_projects_metadata_projection() -> None:
    app: FastAPI = create_app(debug=True)
    app.dependency_overrides[get_current_session] = lambda: SimpleNamespace(
        account_id=ACTOR_ID
    )
    app.dependency_overrides[get_recovery_guard] = lambda: None
    app.dependency_overrides[get_get_project_tree_use_case] = lambda: _GetProjectTree()

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get("/v1/projects/" + str(PROJECT_ID))

    assert response.status_code == 200
    assert response.json()["project"]["name"] == "Plan"
    assert response.json()["folders"][0]["folderId"] == str(FOLDER_ID)


@pytest.mark.asyncio
class _Mutation:
    def __init__(self, result):
        self.result = result
        self.calls: list[tuple] = []

    async def execute(self, *args, **kwargs):
        self.calls.append((args, kwargs))
        return self.result


@pytest.mark.asyncio
async def test_rename_project_maps_fields_and_actor():
    mutation = _Mutation(
        SimpleNamespace(
            project_id=PROJECT_ID, name=WorkspaceName("New"), updated_at=CREATED_AT
        )
    )
    app = create_app(debug=True)
    app.dependency_overrides[get_current_session] = lambda: SimpleNamespace(
        account_id=ACTOR_ID
    )
    app.dependency_overrides[get_recovery_guard] = lambda: None
    app.dependency_overrides[get_rename_project_use_case] = lambda: mutation
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.patch(
            f"/v1/projects/{PROJECT_ID}",
            json={
                "projectId": str(PROJECT_ID),
                "name": "New",
                "idempotencyKey": str(IDEMPOTENCY_KEY),
            },
        )
    assert response.status_code == 200
    assert response.json()["name"] == "New"
    assert mutation.calls[0][0][0] == ACTOR_ID


@pytest.mark.asyncio
async def test_archive_project_conflict_propagates_envelope():
    from app_core.common.exceptions import ConflictError

    class ConflictMutation:
        async def execute(self, *args, **kwargs):
            raise ConflictError("conflict", "WORKSPACE_LIFECYCLE_CONFLICT")

    app = create_app(debug=True)
    app.dependency_overrides[get_current_session] = lambda: SimpleNamespace(
        account_id=ACTOR_ID
    )
    app.dependency_overrides[get_recovery_guard] = lambda: None
    app.dependency_overrides[get_project_lifecycle_use_cases] = lambda: SimpleNamespace(
        archive=ConflictMutation(),
        unarchive=object(),
        trash=object(),
        restore=object(),
    )
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post(
            f"/v1/projects/{PROJECT_ID}/archive",
            json={"projectId": str(PROJECT_ID), "idempotencyKey": str(IDEMPOTENCY_KEY)},
        )
    assert response.status_code == 409
    assert response.json()["errorCode"] == "WORKSPACE_LIFECYCLE_CONFLICT"


@pytest.mark.asyncio
async def test_trash_folder_forwards_actor_and_maps_response():
    mutation = _Mutation(SimpleNamespace(folder_id=FOLDER_ID, updated_at=CREATED_AT))
    app = create_app(debug=True)
    app.dependency_overrides[get_current_session] = lambda: SimpleNamespace(
        account_id=ACTOR_ID
    )
    app.dependency_overrides[get_recovery_guard] = lambda: None
    app.dependency_overrides[get_folder_lifecycle_use_cases] = lambda: SimpleNamespace(
        trash=mutation, restore=object()
    )
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post(
            f"/v1/folders/{FOLDER_ID}/trash",
            json={"folderId": str(FOLDER_ID), "idempotencyKey": str(IDEMPOTENCY_KEY)},
        )
    assert response.status_code == 200
    assert response.json()["folderId"] == str(FOLDER_ID)
    assert mutation.calls[0][0][0] == ACTOR_ID


@pytest.mark.asyncio
async def test_create_workspace_rejects_unregistered_body_fields() -> None:
    app: FastAPI = create_app(debug=True)
    app.dependency_overrides[get_current_session] = lambda: SimpleNamespace(
        account_id=ACTOR_ID
    )
    app.dependency_overrides[get_recovery_guard] = lambda: None
    app.dependency_overrides[get_create_workspace_use_case] = lambda: _CreateWorkspace()

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post(
            "/v1/workspaces",
            json={
                "name": "Roadmap",
                "idempotencyKey": str(IDEMPOTENCY_KEY),
                "ownerAccountId": str(UUID(int=4)),
            },
        )

    assert response.status_code == 422


@pytest.mark.asyncio
async def test_unarchive_project_dispatches_unarchive_not_archive() -> None:
    archive = _Mutation(SimpleNamespace(project_id=PROJECT_ID, updated_at=CREATED_AT))
    unarchive = _Mutation(SimpleNamespace(project_id=PROJECT_ID, updated_at=CREATED_AT))
    app = create_app(debug=True)
    app.dependency_overrides[get_current_session] = lambda: SimpleNamespace(
        account_id=ACTOR_ID
    )
    app.dependency_overrides[get_recovery_guard] = lambda: None
    from types import SimpleNamespace as NS

    app.dependency_overrides[get_project_lifecycle_use_cases] = lambda: NS(
        archive=archive, unarchive=unarchive, trash=object(), restore=object()
    )

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post(
            f"/v1/projects/{PROJECT_ID}/unarchive",
            json={"projectId": str(PROJECT_ID), "idempotencyKey": str(IDEMPOTENCY_KEY)},
        )

    assert response.status_code == 200
    assert unarchive.calls  # unarchive use case executed
    assert not archive.calls  # archive use case must NOT execute
