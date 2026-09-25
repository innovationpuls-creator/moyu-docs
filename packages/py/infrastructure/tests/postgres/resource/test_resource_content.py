from __future__ import annotations

import os
from pathlib import Path
from uuid import uuid4

import pytest
import pytest_asyncio
from alembic import command
from alembic.config import Config
from app_infra.postgres.engine import engine
from app_infra.postgres.resource.checkpoint_repository import (
    PostgresCheckpointRepository,
)
from app_infra.postgres.resource.journal_repository import (
    DuplicateJournalSeqError,
    PostgresJournalRepository,
)
from app_infra.postgres.resource.resource_repository import (
    PostgresResourceRepository,
    ResourceNameConflictError,
)
from app_infra.postgres.test_database_guard import require_isolated_database
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

DATABASE_URL = "postgresql+psycopg://torch@localhost:5432/dom_workspace_lifecycle_test"
_ACCOUNT_IDS = (
    "SELECT account_id FROM auth.accounts "
    "WHERE primary_email LIKE 'resource-content-%@test'"
)
_WORKSPACE_IDS = (
    f"SELECT workspace_id FROM core.workspaces WHERE created_by IN ({_ACCOUNT_IDS})"
)
_PROJECT_IDS = (
    f"SELECT project_id FROM core.projects WHERE workspace_id IN ({_WORKSPACE_IDS})"
)
_RESOURCE_IDS = (
    f"SELECT resource_id FROM core.resources WHERE project_id IN ({_PROJECT_IDS})"
)


@pytest_asyncio.fixture(scope="module", autouse=True)
async def migrated_database() -> None:
    database_url = require_isolated_database(os.environ["DATABASE_URL"])
    assert database_url == DATABASE_URL
    config = Config(str(Path("migrations/postgres/alembic.ini")))
    config.set_main_option("sqlalchemy.url", database_url)
    command.upgrade(config, "head")


@pytest_asyncio.fixture(autouse=True)
async def clean_tables() -> None:
    connection = await engine.connect()
    try:
        session = AsyncSession(connection)
        async with session.begin():
            for table in (
                "collab.resource_search_index",
                "collab.resource_assets",
                "collab.ai_changesets",
                "collab.resource_named_versions",
                "collab.resource_comments",
                "collab.comment_threads",
                "collab.resource_ownership",
                "collab.resource_checkpoints",
                "collab.resource_update_journal",
            ):
                await session.execute(
                    text(f"DELETE FROM {table} WHERE resource_id IN ({_RESOURCE_IDS})")
                )
            await session.execute(
                text(
                    "DELETE FROM core.invitations WHERE "
                    f"workspace_id IN ({_WORKSPACE_IDS}) OR "
                    f"project_id IN ({_PROJECT_IDS}) OR "
                    f"resource_id IN ({_RESOURCE_IDS})"
                )
            )
            for table in ("core.resource_permissions", "core.share_links"):
                await session.execute(
                    text(f"DELETE FROM {table} WHERE resource_id IN ({_RESOURCE_IDS})")
                )
            await session.execute(
                text(
                    "DELETE FROM core.workspace_members "
                    f"WHERE workspace_id IN ({_WORKSPACE_IDS})"
                )
            )
            await session.execute(
                text(
                    "DELETE FROM core.project_members "
                    f"WHERE project_id IN ({_PROJECT_IDS})"
                )
            )
            await session.execute(
                text(
                    f"DELETE FROM core.resources WHERE resource_id IN ({_RESOURCE_IDS})"
                )
            )
            await session.execute(
                text(f"DELETE FROM core.folders WHERE project_id IN ({_PROJECT_IDS})")
            )
            await session.execute(
                text(f"DELETE FROM core.projects WHERE project_id IN ({_PROJECT_IDS})")
            )
            await session.execute(
                text(
                    "DELETE FROM core.workspaces "
                    f"WHERE workspace_id IN ({_WORKSPACE_IDS})"
                )
            )
            await session.execute(
                text(f"DELETE FROM auth.accounts WHERE account_id IN ({_ACCOUNT_IDS})")
            )
        await session.close()
    finally:
        await connection.close()


async def _seed_project(session: AsyncSession) -> str:
    account_id = uuid4()
    workspace_id = uuid4()
    project_id = uuid4()
    await session.execute(
        text(
            "INSERT INTO auth.accounts "
            "(account_id,status,primary_email,normalized_email) "
            "VALUES (:a,'Active',:e,:e)"
        ),
        {"a": account_id, "e": f"resource-content-{account_id}@test"},
    )
    await session.execute(
        text(
            "INSERT INTO core.workspaces "
            "(workspace_id,name,status,created_by,created_at,updated_at) "
            "VALUES (:w,'RC Workspace','Active',:a,now(),now())"
        ),
        {"w": workspace_id, "a": account_id},
    )
    await session.execute(
        text(
            "INSERT INTO core.workspace_members "
            "(workspace_id,account_id,membership_kind) VALUES (:w,:a,'Owner')"
        ),
        {"w": workspace_id, "a": account_id},
    )
    await session.execute(
        text(
            "INSERT INTO core.projects "
            "(project_id,workspace_id,name,normalized_name,lifecycle,"
            "created_by,created_at,updated_at) "
            "VALUES (:p,:w,'RC Project','rc project','Active',:a,now(),now())"
        ),
        {"p": project_id, "w": workspace_id, "a": account_id},
    )
    return str(project_id)


@pytest.mark.asyncio
async def test_journal_monotonic_seq_and_duplicate_rejection() -> None:
    connection = await engine.connect()
    session = AsyncSession(connection)
    try:
        async with session.begin():
            project_id = await _seed_project(session)
            resource = await PostgresResourceRepository(session).create(
                project_id=project_id,
                resource_type="document",
                name="Note",
                normalized_name="note",
            )
        journal = PostgresJournalRepository(session)
        async with session.begin():
            first = await journal.append_op(resource.resource_id, 1, 7, b"op1", "h1")
            second = await journal.append_op(resource.resource_id, 2, 7, b"op2", "h2")
        assert first.journal_seq == 1
        assert second.journal_seq == 2
        async with session.begin():
            with pytest.raises(DuplicateJournalSeqError):
                await journal.append_op(resource.resource_id, 1, 7, b"dup", "hd")
            rows = await journal.read_cursor(resource.resource_id, after_seq=0)
        assert len(rows) == 2
        assert [r.journal_seq for r in rows] == [1, 2]
    finally:
        await session.close()
        await connection.close()


@pytest.mark.asyncio
async def test_checkpoint_write_then_safe_truncation() -> None:
    connection = await engine.connect()
    session = AsyncSession(connection)
    try:
        async with session.begin():
            project_id = await _seed_project(session)
            resource = await PostgresResourceRepository(session).create(
                project_id=project_id,
                resource_type="markdown",
                name="Doc",
                normalized_name="doc",
            )
        journal = PostgresJournalRepository(session)
        checkpoints = PostgresCheckpointRepository(session)
        async with session.begin():
            for seq in (1, 2, 3):
                await journal.append_op(resource.resource_id, seq, 7, b"op", f"h{seq}")
        async with session.begin():
            checkpoint = await checkpoints.write(
                resource.resource_id, 2, {"state": "v2"}
            )
            removed = await checkpoints.truncate_before(resource.resource_id, 2)
        assert checkpoint.base_journal_seq == 2
        assert removed == 2  # journal 1..2 deleted
        async with session.begin():
            remaining = [
                r.journal_seq
                for r in await journal.read_cursor(resource.resource_id, 0)
            ]
        assert remaining == [3]
    finally:
        await session.close()
        await connection.close()


@pytest.mark.asyncio
async def test_resource_sibling_name_conflict_including_trashed() -> None:
    connection = await engine.connect()
    session = AsyncSession(connection)
    try:
        async with session.begin():
            project_id = await _seed_project(session)
            repo = PostgresResourceRepository(session)
            a = await repo.create(
                project_id=project_id,
                resource_type="text",
                name="Shared",
                normalized_name="shared",
            )
            await repo.create(
                project_id=project_id,
                resource_type="text",
                name="Other",
                normalized_name="other",
            )
        repo = PostgresResourceRepository(session)
        async with session.begin():
            with pytest.raises(ResourceNameConflictError):
                await repo.create(
                    project_id=project_id,
                    resource_type="text",
                    name="Shared",
                    normalized_name="shared",
                )
            # Trashed row STILL reserves the sibling name (user ruling)
            await repo.set_lifecycle(a.resource_id, "Trashed")
        async with session.begin():
            with pytest.raises(ResourceNameConflictError):
                await repo.create(
                    project_id=project_id,
                    resource_type="text",
                    name="Shared",
                    normalized_name="shared",
                )
    finally:
        await session.close()
        await connection.close()


@pytest.mark.asyncio
async def test_resource_type_immutable_and_rename_ok() -> None:
    connection = await engine.connect()
    session = AsyncSession(connection)
    try:
        async with session.begin():
            project_id = await _seed_project(session)
            repo = PostgresResourceRepository(session)
            a = await repo.create(
                project_id=project_id,
                resource_type="code",
                name="main",
                normalized_name="main",
            )
        repo = PostgresResourceRepository(session)
        async with session.begin():
            renamed = await repo.rename(a.resource_id, "main.py", "main.py")
        assert renamed.name == "main.py"
        # no UPDATE path exposes resource_type changes -> read back unchanged
        fetched = await repo.get(a.resource_id)
        assert fetched is not None
        assert fetched.resource_type == "code"
    finally:
        await session.close()
        await connection.close()


@pytest.mark.asyncio
async def test_rollback_keeps_journal_and_checkpoint_rows() -> None:
    connection = await engine.connect()
    session = AsyncSession(connection)
    try:
        async with session.begin():
            project_id = await _seed_project(session)
            resource = await PostgresResourceRepository(session).create(
                project_id=project_id,
                resource_type="document",
                name="R",
                normalized_name="r",
            )
        journal = PostgresJournalRepository(session)
        checkpoints = PostgresCheckpointRepository(session)
        try:
            async with session.begin():
                await journal.append_op(resource.resource_id, 1, 7, b"op", "h1")
                await checkpoints.write(resource.resource_id, 1, {"state": "v1"})
                raise RuntimeError("boom")
        except RuntimeError:
            pass
        async with session.begin():
            assert await journal.max_seq(resource.resource_id) == 0
            assert await checkpoints.latest(resource.resource_id) is None
    finally:
        await session.close()
        await connection.close()
