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
from app_core.history.domain import VersionKind
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
from sqlalchemy.ext.asyncio import AsyncSession

DATABASE_URL = "postgresql+psycopg://torch@localhost:5432/dom_workspace_lifecycle_test"
_ACCOUNT_IDS = (
    "SELECT account_id FROM auth.accounts WHERE primary_email LIKE 'hist-%@test'"
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


async def _seed(session: AsyncSession) -> tuple[str, object]:
    account_id = uuid4()
    workspace_id = uuid4()
    project_id = uuid4()
    await session.execute(
        text(
            "INSERT INTO auth.accounts "
            "(account_id,status,primary_email,normalized_email) "
            "VALUES (:a,'Active',:e,:e)"
        ),
        {"a": account_id, "e": f"hist-{account_id}@test"},
    )
    await session.execute(
        text(
            "INSERT INTO core.workspaces "
            "(workspace_id,name,status,created_by,created_at,updated_at) "
            "VALUES (:w,'H','Active',:a,now(),now())"
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
            "VALUES (:p,:w,'P','p','Active',:a,now(),now())"
        ),
        {"p": project_id, "w": workspace_id, "a": account_id},
    )
    resource = await PostgresResourceRepository(session).create(
        project_id=project_id,
        resource_type="document",
        name="Doc",
        normalized_name="doc",
    )
    return str(account_id), resource


@pytest.mark.asyncio
async def test_history_timeline_restore_and_named_version() -> None:
    connection = await engine.connect()
    session = AsyncSession(connection)
    try:
        async with session.begin():
            account_id, resource = await _seed(session)
            await PostgresResourceOwnershipRepository(session).grant(
                resource.resource_id, account_id
            )
        journal = PostgresJournalRepository(session)
        checkpoints = PostgresCheckpointRepository(session)
        history = PostgresHistoryRepository(session)
        async with session.begin():
            for seq in range(1, 6):
                await journal.append_op(resource.resource_id, seq, 1, b"op", f"h{seq}")
            await checkpoints.write(resource.resource_id, 5, {"v": "base"})
        restore = RestoreAtVersion(
            history,
            PostgresResourceRepository(session),
            journal,
            checkpoints,
            apply=lambda state, op: {**state, "seq": op.journal_seq},
        )
        async with session.begin():
            node = await restore.execute(resource.resource_id, 5, actor_id=account_id)
        assert node.kind == VersionKind.RESTORE
        async with session.begin():
            await CreateNamedVersion(history).execute(
                resource.resource_id,
                "API 确认",
                base_journal_seq=6,
                created_by=account_id,
            )
        async with session.begin():
            nodes = await ListVersions(history).execute(resource.resource_id)
        kinds = [n.kind for n in nodes]
        assert VersionKind.NAMED in kinds
        assert VersionKind.RESTORE in kinds
        assert VersionKind.AUTOMATIC in kinds
        assert nodes[0].base_journal_seq >= 6  # newest first
        async with session.begin():
            base = await checkpoints.latest(resource.resource_id)
        assert base is not None and base.base_journal_seq == 6
    finally:
        await session.close()
        await connection.close()
