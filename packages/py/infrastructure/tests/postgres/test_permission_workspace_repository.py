from __future__ import annotations

import asyncio
import hashlib
import os
from pathlib import Path
from uuid import uuid4

import pytest
import pytest_asyncio
from alembic import command
from alembic.config import Config
from app_infra.postgres.engine import engine
from app_infra.postgres.test_database_guard import require_isolated_database
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

DATABASE_URL = "postgresql+psycopg://torch@localhost:5432/dom_workspace_lifecycle_test"


@pytest_asyncio.fixture(scope="module", autouse=True)
async def migrated_database() -> None:
    database_url = require_isolated_database(os.environ["DATABASE_URL"])
    assert database_url == DATABASE_URL
    identity_engine = create_async_engine(database_url)
    try:
        async with identity_engine.connect() as connection:
            identity = (
                await connection.execute(
                    text("SELECT current_database(), current_user")
                )
            ).one()
    finally:
        await identity_engine.dispose()
    if identity != ("dom_workspace_lifecycle_test", "torch"):
        raise RuntimeError(f"Unexpected database identity: {identity!r}")
    config = Config(str(Path("migrations/postgres/alembic.ini")))
    config.set_main_option("sqlalchemy.url", database_url)
    command.upgrade(config, "head")


@pytest_asyncio.fixture
async def db_session() -> AsyncSession:
    async with engine.connect() as connection:
        transaction = await connection.begin()
        factory = async_sessionmaker(
            bind=connection,
            expire_on_commit=False,
            class_=AsyncSession,
            join_transaction_mode="create_savepoint",
        )
        async with factory() as session:
            yield session
            await session.rollback()
        await transaction.rollback()


async def _account(session: AsyncSession, status: str = "Active"):
    account_id = uuid4()
    await session.execute(
        text(
            "INSERT INTO auth.accounts "
            "(account_id, status, primary_email, normalized_email) "
            "VALUES (:id, :status, :email, :email)"
        ),
        {"id": account_id, "status": status, "email": f"{account_id}@example.test"},
    )
    return account_id


async def _workspace(session: AsyncSession, status: str = "Active"):
    workspace_id = uuid4()
    creator_id = await _account(session)
    await session.execute(
        text(
            "INSERT INTO core.workspaces (workspace_id, name, status, created_by) "
            "VALUES (:id, 'Research', :status, :creator)"
        ),
        {"id": workspace_id, "status": status, "creator": creator_id},
    )
    return workspace_id, creator_id


@pytest.mark.asyncio
async def test_partial_unique_owner_index_exists(db_session: AsyncSession) -> None:
    indexes = await db_session.execute(
        text(
            "SELECT i.indisunique, pg_get_expr(i.indpred, i.indrelid) AS predicate "
            "FROM pg_index AS i JOIN pg_class AS t ON t.oid=i.indrelid "
            "JOIN pg_namespace AS n ON n.oid=t.relnamespace "
            "WHERE n.nspname='core' AND t.relname='workspace_members'"
        )
    )
    assert any(
        row.indisunique
        and row.predicate is not None
        and "membership_kind" in row.predicate
        and "Owner" in row.predicate
        for row in indexes
    )


@pytest.mark.asyncio
async def test_memberships_have_composite_primary_key_foreign_keys_and_kind_check(
    db_session: AsyncSession,
) -> None:
    workspace_id, owner_id = await _workspace(db_session)
    from app_infra.postgres.permission_workspace_repository import (
        PostgresWorkspaceMembershipRepository,
    )

    repository = PostgresWorkspaceMembershipRepository(db_session)
    await repository.grant_initial_owner(workspace_id, owner_id)
    with pytest.raises(IntegrityError):
        async with db_session.begin_nested():
            await repository.grant_initial_owner(workspace_id, owner_id)
    with pytest.raises(IntegrityError):
        async with db_session.begin_nested():
            await db_session.execute(
                text(
                    "INSERT INTO core.workspace_members "
                    "(workspace_id, account_id, membership_kind) "
                    "VALUES (:workspace_id, :account_id, 'Administrator')"
                ),
                {
                    "workspace_id": workspace_id,
                    "account_id": await _account(db_session),
                },
            )
    assert await repository.get_current_workspace_owner(workspace_id) == owner_id


@pytest.mark.asyncio
async def test_workspace_insert_with_owner_in_same_transaction_is_valid(
    db_session: AsyncSession,
) -> None:
    owner_id = await _account(db_session)
    from app_infra.postgres.permission_workspace_repository import (
        PostgresWorkspaceMembershipRepository,
    )

    workspace_id = uuid4()
    await db_session.execute(
        text(
            "INSERT INTO core.workspaces "
            "(workspace_id, name, created_by) "
            "VALUES (:id, 'Owned at insert', :owner)"
        ),
        {"id": workspace_id, "owner": owner_id},
    )
    await PostgresWorkspaceMembershipRepository(db_session).grant_initial_owner(
        workspace_id, owner_id
    )
    await db_session.flush()


@pytest.mark.asyncio
@pytest.mark.parametrize("workspace_status", ["Deleted", "DeletionPending"])
async def test_initial_owner_grant_rejects_non_active_workspace(
    db_session: AsyncSession, workspace_status: str
) -> None:
    from app_core.common.exceptions import ConflictError
    from app_infra.postgres.permission_workspace_repository import (
        PostgresWorkspaceMembershipRepository,
    )

    workspace_id, owner_id = await _workspace(db_session, workspace_status)
    repository = PostgresWorkspaceMembershipRepository(db_session)
    with pytest.raises(ConflictError) as error:
        await repository.grant_initial_owner(workspace_id, owner_id)
    assert error.value.error_code == "WORKSPACE_LIFECYCLE_CONFLICT"
    if workspace_status == "Deleted":
        assert await repository.get_current_workspace_owner(workspace_id) is None
    else:
        from app_core.permission.domain.workspace_membership import (
            PermissionDependencyError,
        )

        with pytest.raises(PermissionDependencyError):
            await repository.get_current_workspace_owner(workspace_id)


@pytest.mark.asyncio
async def test_initial_owner_grant_rejects_non_active_account(
    db_session: AsyncSession,
) -> None:
    from app_core.common.exceptions import PermissionDeniedError
    from app_infra.postgres.permission_workspace_repository import (
        PostgresWorkspaceMembershipRepository,
    )

    inactive_account = await _account(db_session, "Disabled")
    workspace_id, _ = await _workspace(db_session)
    repository = PostgresWorkspaceMembershipRepository(db_session)
    with pytest.raises(PermissionDeniedError) as error:
        await repository.grant_initial_owner(workspace_id, inactive_account)
    assert error.value.error_code == "WORKSPACE_CREATION_REQUIRES_ACTIVE_ACCOUNT"
    from app_core.permission.domain.workspace_membership import (
        PermissionDependencyError,
    )

    with pytest.raises(PermissionDependencyError):
        await repository.get_current_workspace_owner(workspace_id)


@pytest.mark.asyncio
async def test_ownerless_live_workspace_is_rejected_at_deferred_constraint(
    db_session: AsyncSession,
) -> None:
    owner_id = await _account(db_session)
    with pytest.raises(IntegrityError):
        async with db_session.begin_nested():
            await db_session.execute(
                text(
                    "INSERT INTO core.workspaces "
                    "(workspace_id, name, created_by) "
                    "VALUES (:id, 'Ownerless', :owner)"
                ),
                {"id": uuid4(), "owner": owner_id},
            )
            await db_session.execute(text("SET CONSTRAINTS ALL IMMEDIATE"))


@pytest.mark.asyncio
async def test_membership_foreign_keys_reject_unknown_workspace_and_account(
    db_session: AsyncSession,
) -> None:
    with pytest.raises(IntegrityError):
        async with db_session.begin_nested():
            await db_session.execute(
                text(
                    "INSERT INTO core.workspace_members "
                    "(workspace_id, account_id, membership_kind) "
                    "VALUES (:workspace_id, :account_id, 'Owner')"
                ),
                {"workspace_id": uuid4(), "account_id": uuid4()},
            )
    workspace_id, owner_id = await _workspace(db_session)
    with pytest.raises(IntegrityError):
        async with db_session.begin_nested():
            await db_session.execute(
                text(
                    "INSERT INTO core.workspace_members "
                    "(workspace_id, account_id, membership_kind) "
                    "VALUES (:workspace_id, :account_id, 'Owner')"
                ),
                {"workspace_id": workspace_id, "account_id": uuid4()},
            )
    unknown_workspace = uuid4()
    known_account = owner_id
    with pytest.raises(IntegrityError):
        async with db_session.begin_nested():
            await db_session.execute(
                text(
                    "INSERT INTO core.workspace_members "
                    "(workspace_id, account_id, membership_kind) "
                    "VALUES (:workspace_id, :account_id, 'Member')"
                ),
                {"workspace_id": unknown_workspace, "account_id": known_account},
            )


@pytest.mark.asyncio
async def test_initial_owner_and_duplicate_transfer_keep_one_owner(
    db_session: AsyncSession,
) -> None:
    from app_infra.postgres.permission_workspace_repository import (
        PostgresWorkspaceMembershipRepository,
    )

    workspace_id, original_owner = await _workspace(db_session)
    target = await _account(db_session)
    repository = PostgresWorkspaceMembershipRepository(db_session)
    await repository.grant_initial_owner(workspace_id, original_owner)
    await db_session.execute(
        text(
            "INSERT INTO core.workspace_members "
            "(workspace_id, account_id, membership_kind) "
            "VALUES (:workspace_id, :account_id, 'Member')"
        ),
        {"workspace_id": workspace_id, "account_id": target},
    )
    with pytest.raises(IntegrityError):
        async with db_session.begin_nested():
            await repository.grant_initial_owner(workspace_id, target)
    result = await repository.transfer_owner_idempotently(
        original_owner, workspace_id, target, "transfer-1"
    )
    assert result.previous_owner_account_id == original_owner
    assert result.new_owner_account_id == target
    assert await repository.get_current_workspace_owner(workspace_id) == target
    count = await db_session.scalar(
        text(
            "SELECT count(*) FROM core.workspace_members "
            "WHERE workspace_id=:workspace_id AND membership_kind='Owner'"
        ),
        {"workspace_id": workspace_id},
    )
    assert count == 1


@pytest.mark.asyncio
async def test_database_rejects_zero_owner_at_commit() -> None:
    async with engine.connect() as connection:
        session = AsyncSession(connection, expire_on_commit=False)
        workspace_id, owner = await _workspace(session)
        from app_infra.postgres.permission_workspace_repository import (
            PostgresWorkspaceMembershipRepository,
        )

        await PostgresWorkspaceMembershipRepository(session).grant_initial_owner(
            workspace_id, owner
        )
        await session.execute(
            text("DELETE FROM core.workspace_members WHERE workspace_id=:id"),
            {"id": workspace_id},
        )
        with pytest.raises(IntegrityError):
            await session.commit()
        await session.rollback()
        await session.close()


@pytest.mark.asyncio
async def test_database_rejects_multiple_owners() -> None:
    async with engine.connect() as connection:
        session = AsyncSession(connection, expire_on_commit=False)
        workspace_id, owner = await _workspace(session)
        second = await _account(session)
        from app_infra.postgres.permission_workspace_repository import (
            PostgresWorkspaceMembershipRepository,
        )

        await PostgresWorkspaceMembershipRepository(session).grant_initial_owner(
            workspace_id, owner
        )
        with pytest.raises(IntegrityError):
            await session.execute(
                text(
                    "INSERT INTO core.workspace_members "
                    "(workspace_id, account_id, membership_kind) "
                    "VALUES (:workspace_id, :account_id, 'Owner')"
                ),
                {"workspace_id": workspace_id, "account_id": second},
            )
        await session.rollback()
        await session.close()


@pytest.mark.asyncio
async def test_workspace_owner_inherits_project_manage_without_project_rows(
    db_session: AsyncSession,
) -> None:
    workspace_id, owner = await _workspace(db_session)
    creator = await db_session.scalar(
        text("SELECT created_by FROM core.workspaces WHERE workspace_id=:id"),
        {"id": workspace_id},
    )
    project_id = uuid4()
    await db_session.execute(
        text(
            "INSERT INTO core.projects "
            "(project_id, workspace_id, name, normalized_name, created_by) "
            "VALUES (:id, :workspace_id, 'Plan', 'plan', :creator)"
        ),
        {"id": project_id, "workspace_id": workspace_id, "creator": creator},
    )
    from app_infra.postgres.permission_workspace_repository import (
        PostgresWorkspaceMembershipRepository,
    )

    repository = PostgresWorkspaceMembershipRepository(db_session)
    await repository.grant_initial_owner(workspace_id, owner)
    assert await repository.can_manage_project(owner, project_id)
    project_members = await db_session.scalar(
        text(
            "SELECT count(*) FROM core.workspace_members "
            "WHERE workspace_id=:id AND account_id=:owner"
        ),
        {"id": workspace_id, "owner": owner},
    )
    assert project_members == 1


@pytest.mark.asyncio
async def test_membership_workspace_id_cannot_move_and_orphan_source(
    db_session: AsyncSession,
) -> None:
    from app_infra.postgres.permission_workspace_repository import (
        PostgresWorkspaceMembershipRepository,
    )

    source_workspace, owner = await _workspace(db_session)
    target_workspace, target_owner = await _workspace(db_session)
    repository = PostgresWorkspaceMembershipRepository(db_session)
    await repository.grant_initial_owner(source_workspace, owner)
    await repository.grant_initial_owner(target_workspace, target_owner)
    with pytest.raises(IntegrityError):
        async with db_session.begin_nested():
            await db_session.execute(
                text(
                    "UPDATE core.workspace_members SET workspace_id=:target "
                    "WHERE workspace_id=:source AND account_id=:owner"
                ),
                {
                    "target": target_workspace,
                    "source": source_workspace,
                    "owner": owner,
                },
            )
    assert await repository.get_current_workspace_owner(source_workspace) == owner


@pytest.mark.asyncio
async def test_transfer_rejects_missing_or_deleted_workspace_before_claim(
    db_session: AsyncSession,
) -> None:
    from app_core.common.exceptions import NotFoundError
    from app_infra.postgres.permission_workspace_repository import (
        PostgresWorkspaceMembershipRepository,
    )

    repository = PostgresWorkspaceMembershipRepository(db_session)
    owner_id = uuid4()
    missing_workspace_id = uuid4()
    with pytest.raises(NotFoundError) as missing_error:
        await repository.transfer_owner_idempotently(
            owner_id, missing_workspace_id, uuid4(), "missing-workspace"
        )
    assert missing_error.value.error_code == "WORKSPACE_NOT_FOUND"
    assert (
        await db_session.scalar(
            text(
                "SELECT count(*) FROM integration.idempotency_records "
                "WHERE idempotency_key=:key"
            ),
            {"key": "workspace-owner-transfer:missing-workspace"},
        )
        == 0
    )

    deleted_workspace, deleted_owner = await _workspace(db_session, "Deleted")
    with pytest.raises(NotFoundError) as deleted_error:
        await repository.transfer_owner_idempotently(
            deleted_owner, deleted_workspace, uuid4(), "deleted-workspace"
        )
    assert deleted_error.value.error_code == "WORKSPACE_NOT_FOUND"
    assert (
        await db_session.scalar(
            text(
                "SELECT count(*) FROM integration.idempotency_records "
                "WHERE idempotency_key=:key"
            ),
            {"key": "workspace-owner-transfer:deleted-workspace"},
        )
        == 0
    )


@pytest.mark.asyncio
async def test_transfer_replay_fingerprint_and_current_owner_are_atomic(
    db_session: AsyncSession,
) -> None:
    from app_core.common.exceptions import IdempotencyConflictError
    from app_infra.postgres.permission_workspace_repository import (
        PostgresWorkspaceMembershipRepository,
    )

    workspace_id, owner = await _workspace(db_session)
    target = await _account(db_session)
    other_target = await _account(db_session)
    repository = PostgresWorkspaceMembershipRepository(db_session)
    await repository.grant_initial_owner(workspace_id, owner)
    await db_session.execute(
        text(
            "INSERT INTO core.workspace_members "
            "(workspace_id, account_id, membership_kind) "
            "VALUES (:workspace_id, :account_id, 'Member')"
        ),
        {"workspace_id": workspace_id, "account_id": target},
    )
    await repository.add_member(workspace_id, other_target)
    key = "transfer-fingerprint-test"
    first = await repository.transfer_owner_idempotently(
        owner, workspace_id, target, key
    )
    replay = await repository.transfer_owner_idempotently(
        owner, workspace_id, target, key
    )
    assert replay == first
    with pytest.raises(IdempotencyConflictError):
        await repository.transfer_owner_idempotently(
            owner, workspace_id, other_target, key
        )
    assert await repository.get_current_workspace_owner(workspace_id) == target
    digest = hashlib.sha256(f"{workspace_id}:{owner}:{target}".encode()).hexdigest()
    stored = await db_session.scalar(
        text(
            "SELECT response FROM integration.idempotency_records "
            "WHERE idempotency_key=:key"
        ),
        {"key": f"workspace-owner-transfer:{key}"},
    )
    assert digest in stored


@pytest.mark.asyncio
async def test_transfer_rejects_nonmember_and_inactive_account(
    db_session: AsyncSession,
) -> None:
    from app_core.common.exceptions import ConflictError
    from app_infra.postgres.permission_workspace_repository import (
        PostgresWorkspaceMembershipRepository,
    )

    workspace_id, owner = await _workspace(db_session)
    inactive = await _account(db_session, "Disabled")
    repository = PostgresWorkspaceMembershipRepository(db_session)
    await repository.grant_initial_owner(workspace_id, owner)
    await repository.add_member(workspace_id, inactive)
    with pytest.raises(ConflictError):
        await repository.transfer_owner_idempotently(
            owner, workspace_id, uuid4(), "missing-member"
        )
    with pytest.raises(ConflictError):
        await repository.transfer_owner_idempotently(
            owner, workspace_id, inactive, "inactive-target"
        )


@pytest.mark.asyncio
async def test_sole_owned_workspace_projection_includes_id_and_ignores_deleted(
    db_session: AsyncSession,
) -> None:
    from app_infra.postgres.permission_workspace_repository import (
        PostgresWorkspaceMembershipRepository,
    )

    repository = PostgresWorkspaceMembershipRepository(db_session)
    workspace_id, owner = await _workspace(db_session)
    await repository.grant_initial_owner(workspace_id, owner)
    assert await repository.sole_owned_workspace(owner) == (
        True,
        "Research",
        workspace_id,
    )
    assert await repository.has_sole_ownership(owner) == (True, "Research")
    await db_session.execute(
        text("UPDATE core.workspaces SET status='Deleted' WHERE workspace_id=:id"),
        {"id": workspace_id},
    )
    assert await repository.has_sole_ownership(owner) == (False, None)
    assert await repository.sole_owned_workspace(owner) == (False, None, None)


@pytest.mark.asyncio
async def test_sole_owned_workspace_projection_fails_closed_for_fragmented_state(
    db_session: AsyncSession,
) -> None:
    from app_infra.postgres.permission_workspace_repository import (
        PostgresWorkspaceMembershipRepository,
    )

    repository = PostgresWorkspaceMembershipRepository(db_session)
    first_workspace, owner = await _workspace(db_session)
    second_workspace, _ = await _workspace(db_session)
    await repository.grant_initial_owner(first_workspace, owner)
    await db_session.execute(
        text(
            "INSERT INTO core.workspace_members "
            "(workspace_id,account_id,membership_kind) "
            "VALUES (:workspace_id,:account_id,'Owner')"
        ),
        {"workspace_id": second_workspace, "account_id": owner},
    )
    projected = await repository.sole_owned_workspace(owner)
    assert projected[0] is True
    assert projected[1] == "Research"
    assert projected[2] in {first_workspace, second_workspace}
    assert await repository.has_sole_ownership(owner) == (True, None)


@pytest.mark.asyncio
async def test_missing_owner_for_live_workspace_fails_closed(
    db_session: AsyncSession,
) -> None:
    from app_core.permission.domain.workspace_membership import (
        PermissionDependencyError,
    )
    from app_infra.postgres.permission_workspace_repository import (
        PostgresWorkspaceMembershipRepository,
    )

    workspace_id, _ = await _workspace(db_session)
    repository = PostgresWorkspaceMembershipRepository(db_session)
    with pytest.raises(PermissionDependencyError):
        await repository.get_current_workspace_owner(workspace_id)


@pytest.mark.asyncio
async def test_owner_transfer_audit_and_outbox_share_transaction(
    db_session: AsyncSession,
) -> None:
    from app_infra.postgres.permission_workspace_repository import (
        PostgresWorkspaceMembershipRepository,
    )

    workspace_id, owner = await _workspace(db_session)
    target = await _account(db_session)
    repository = PostgresWorkspaceMembershipRepository(db_session)
    await repository.grant_initial_owner(workspace_id, owner)
    await db_session.execute(
        text(
            "INSERT INTO core.workspace_members "
            "(workspace_id, account_id, membership_kind) "
            "VALUES (:workspace_id, :account_id, 'Member')"
        ),
        {"workspace_id": workspace_id, "account_id": target},
    )
    await repository.transfer_owner_idempotently(
        owner, workspace_id, target, "audit-outbox"
    )
    audit_action = await db_session.scalar(
        text("SELECT action FROM audit.entries WHERE workspace_id=:id"),
        {"id": workspace_id},
    )
    events = (
        (
            await db_session.execute(
                text(
                    "SELECT event_type, schema_version, payload "
                    "FROM integration.outbox_events WHERE aggregate_id=:id"
                ),
                {"id": workspace_id},
            )
        )
        .mappings()
        .all()
    )
    assert audit_action == "WorkspaceOwnerTransferred"
    assert len(events) == 2
    assert {event["event_type"] for event in events} == {"event.permission.changed.v1"}
    assert {event["schema_version"] for event in events} == {"1.0.0"}
    changes = {event["payload"]["payload"]["accountId"]: event for event in events}
    assert changes[str(owner)]["payload"]["payload"]["role"] == "Member"
    assert changes[str(target)]["payload"]["payload"]["role"] == "Owner"
    assert all(
        event["payload"]["payload"]["action"] == "owner_transferred" for event in events
    )


@pytest.mark.asyncio
async def test_same_key_concurrent_transfer_returns_same_result() -> None:
    from app_infra.postgres.permission_workspace_repository import (
        PostgresWorkspaceMembershipRepository,
    )

    async with engine.connect() as setup_connection:
        setup = AsyncSession(setup_connection, expire_on_commit=False)
        workspace_id, owner = await _workspace(setup)
        target = await _account(setup)
        repository = PostgresWorkspaceMembershipRepository(setup)
        await repository.grant_initial_owner(workspace_id, owner)
        await repository.add_member(workspace_id, target)
        await setup.commit()
        await setup.close()

    barrier = asyncio.Barrier(2)
    key = f"same-key-{uuid4()}"

    async def retry_transfer():
        async with engine.connect() as connection:
            session = AsyncSession(connection, expire_on_commit=False)
            try:
                await barrier.wait()
                result = await PostgresWorkspaceMembershipRepository(
                    session
                ).transfer_owner_idempotently(owner, workspace_id, target, key)
                await session.commit()
                return result
            except Exception:
                await session.rollback()
                raise
            finally:
                await session.close()

    first, second = await asyncio.gather(retry_transfer(), retry_transfer())
    assert first == second


@pytest.mark.asyncio
async def test_independent_sessions_serialize_owner_transfer_race() -> None:
    from app_core.common.exceptions import ConflictError
    from app_infra.postgres.permission_workspace_repository import (
        PostgresWorkspaceMembershipRepository,
    )

    async with engine.connect() as setup_connection:
        setup = AsyncSession(setup_connection, expire_on_commit=False)
        workspace_id, owner = await _workspace(setup)
        first_target, second_target = await _account(setup), await _account(setup)
        setup_repository = PostgresWorkspaceMembershipRepository(setup)
        await setup_repository.grant_initial_owner(workspace_id, owner)
        await setup_repository.add_member(workspace_id, first_target)
        await setup_repository.add_member(workspace_id, second_target)
        await setup.commit()
        await setup.close()

    barrier = asyncio.Barrier(2)

    async def transfer(target, key):
        async with engine.connect() as connection:
            session = AsyncSession(connection, expire_on_commit=False)
            try:
                await barrier.wait()
                result = await PostgresWorkspaceMembershipRepository(
                    session
                ).transfer_owner_idempotently(owner, workspace_id, target, key)
                await session.commit()
                return result
            except Exception as error:
                await session.rollback()
                return error
            finally:
                await session.close()

    outcomes = await asyncio.gather(
        transfer(first_target, f"race-one-{uuid4()}"),
        transfer(second_target, f"race-two-{uuid4()}"),
        return_exceptions=True,
    )
    successes = [item for item in outcomes if not isinstance(item, BaseException)]
    failures = [item for item in outcomes if isinstance(item, BaseException)]
    assert len(successes) == 1, outcomes
    assert len(failures) == 1 and isinstance(failures[0], ConflictError), outcomes
    async with engine.connect() as connection:
        count = await connection.scalar(
            text(
                "SELECT count(*) FROM core.workspace_members "
                "WHERE workspace_id=:id AND membership_kind='Owner'"
            ),
            {"id": workspace_id},
        )
    assert count == 1
