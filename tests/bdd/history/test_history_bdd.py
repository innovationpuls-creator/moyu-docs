"""History BDD — real chain evidence (no HTTP), guarded isolated DB."""

from __future__ import annotations

import os
from pathlib import Path
from uuid import uuid4

import pytest
import pytest_asyncio
from alembic import command
from alembic.config import Config
from app_core.history.application import (
    CreateNamedVersion,
    ListVersions,
    RestoreAtVersion,
)
from app_core.history.domain import NamedVersionLabelConflictError, VersionKind
from app_infra.postgres.engine import engine
from app_infra.postgres.history.history_repository import PostgresHistoryRepository
from app_infra.postgres.resource.checkpoint_repository import (
    PostgresCheckpointRepository,
)
from app_infra.postgres.resource.journal_repository import PostgresJournalRepository
from app_infra.postgres.resource.resource_repository import PostgresResourceRepository
from app_infra.postgres.resource_ownership_repository import (
    PostgresResourceOwnershipRepository,
)
from app_infra.postgres.test_database_guard import require_isolated_database
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

DATABASE_URL = "postgresql+psycopg://torch@localhost:5432/dom_workspace_lifecycle_test"


@pytest_asyncio.fixture(scope="module", autouse=True)
async def migrated_database() -> None:
    database_url = require_isolated_database(os.environ["DATABASE_URL"])
    assert database_url == DATABASE_URL
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


@pytest_asyncio.fixture(autouse=True)
async def clean_tables() -> None:
    connection = await engine.connect()
    try:
        session = AsyncSession(connection)
        async with session.begin():
            for t in (
                "collab.resource_search_index",
                "collab.resource_assets",
                "collab.ai_changesets",
                "collab.resource_named_versions",
                "collab.resource_comments",
                "collab.resource_ownership",
                "collab.resource_checkpoints",
                "collab.resource_update_journal",
                "core.resources",
                "core.workspace_members",
                "core.folders",
                "core.projects",
                "core.workspaces",
            ):
                await session.execute(text(f"DELETE FROM {t}"))
            await session.execute(
                text("DELETE FROM auth.accounts WHERE primary_email LIKE 'hsv-%@test'")
            )
        await session.close()
    finally:
        await connection.close()


async def _seed_resource(db_session: AsyncSession):
    account_id = uuid4()
    workspace_id = uuid4()
    project_id = uuid4()
    await db_session.execute(
        text(
            "INSERT INTO auth.accounts "
            "(account_id,status,primary_email,normalized_email) "
            "VALUES (:a,'Active',:e,:e)"
        ),
        {"a": account_id, "e": f"hsv-{account_id}@test"},
    )
    await db_session.execute(
        text(
            "INSERT INTO core.workspaces "
            "(workspace_id,name,status,created_by,created_at,updated_at) "
            "VALUES (:w,'H','Active',:a,now(),now())"
        ),
        {"w": workspace_id, "a": account_id},
    )
    await db_session.execute(
        text(
            "INSERT INTO core.workspace_members "
            "(workspace_id,account_id,membership_kind) VALUES (:w,:a,'Owner')"
        ),
        {"w": workspace_id, "a": account_id},
    )
    await db_session.execute(
        text(
            "INSERT INTO core.projects "
            "(project_id,workspace_id,name,normalized_name,lifecycle,"
            "created_by,created_at,updated_at) "
            "VALUES (:p,:w,'P','p','Active',:a,now(),now())"
        ),
        {"p": project_id, "w": workspace_id, "a": account_id},
    )
    resource = await PostgresResourceRepository(db_session).create(
        project_id=project_id,
        resource_type="document",
        name="Doc",
        normalized_name="doc",
    )
    await PostgresResourceOwnershipRepository(db_session).grant(
        resource.resource_id, account_id
    )
    return account_id, resource


async def _build_history(session):
    return PostgresHistoryRepository(session)


@pytest.mark.asyncio
async def test_timeline_contains_all_kinds_and_restore_is_new_current(
    db_session: AsyncSession,
) -> None:
    async with db_session.begin():
        account_id, resource = await _seed_resource(db_session)
    journal = PostgresJournalRepository(db_session)
    checkpoints = PostgresCheckpointRepository(db_session)
    history = await _build_history(db_session)
    async with db_session.begin():
        for seq in range(1, 5):
            await journal.append_op(resource.resource_id, seq, 1, b"op", f"h{seq}")
        await checkpoints.write(resource.resource_id, 4, {"v": "current"})
        await CreateNamedVersion(history).execute(
            resource.resource_id, "v4-name", base_journal_seq=4, created_by=account_id
        )
    restore = RestoreAtVersion(
        history,
        PostgresResourceRepository(db_session),
        journal,
        checkpoints,
        apply=lambda state, op: {**state, "seq": op.journal_seq},
    )
    async with db_session.begin():
        node = await restore.execute(resource.resource_id, 2, actor_id=account_id)
    assert node.kind == VersionKind.RESTORE
    async with db_session.begin():
        nodes = await ListVersions(history).execute(resource.resource_id)
    kinds = {n.kind for n in nodes}
    assert kinds == {VersionKind.AUTOMATIC, VersionKind.NAMED, VersionKind.RESTORE}
    assert nodes[0].base_journal_seq == 5  # restore = newest current
    async with db_session.begin():
        ck = await checkpoints.latest(resource.resource_id)
    assert ck is not None and ck.base_journal_seq == 5
    # previous current (v4 checkpoint) still exists
    async with db_session.begin():
        count = await db_session.scalar(
            text(
                "SELECT count(*) FROM collab.resource_checkpoints WHERE resource_id=:id"
            ),
            {"id": resource.resource_id},
        )
    assert count >= 2


@pytest.mark.asyncio
async def test_named_version_label_conflict(db_session: AsyncSession) -> None:
    async with db_session.begin():
        _, resource = await _seed_resource(db_session)
    history = await _build_history(db_session)
    async with db_session.begin():
        await CreateNamedVersion(history).execute(
            resource.resource_id, "dup-label", base_journal_seq=1
        )
        with pytest.raises(NamedVersionLabelConflictError):
            await CreateNamedVersion(history).execute(
                resource.resource_id, "dup-label", base_journal_seq=2
            )
