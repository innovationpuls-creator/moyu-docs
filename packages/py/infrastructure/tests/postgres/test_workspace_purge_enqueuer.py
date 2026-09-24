from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pytest
import pytest_asyncio
from alembic import command
from alembic.config import Config
from app_infra.postgres.engine import engine
from app_infra.postgres.test_database_guard import require_isolated_database
from app_infra.postgres.workspace_purge_enqueuer import PostgresWorkspacePurgeEnqueuer
from app_infra.postgres.workspace_purge_repository import (
    PostgresWorkspacePurgeRepository,
)
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

DATABASE_URL = "postgresql+psycopg://torch@localhost:5432/dom_workspace_lifecycle_test"


class Cleanup:
    async def remove_workspace_memberships(self, workspace_id):
        return None


@pytest_asyncio.fixture(scope="module", autouse=True)
async def migrated_database() -> None:
    database_url = require_isolated_database(os.environ["DATABASE_URL"])
    assert database_url == DATABASE_URL
    config = Config(str(Path("migrations/postgres/alembic.ini")))
    config.set_main_option("sqlalchemy.url", database_url)
    command.upgrade(config, "head")


@pytest.mark.asyncio
async def test_duplicate_scans_create_one_task_row() -> None:
    connection = await engine.connect()
    session = AsyncSession(connection)
    workspace_id = uuid4()
    account_id = uuid4()
    try:
        async with session.begin():
            await session.execute(
                text(
                    "DELETE FROM work.tasks WHERE task_type='lifecycle.purge.workspace'"
                )
            )
            await session.execute(
                text(
                    "DELETE FROM core.workspace_members "
                    "WHERE workspace_id IN (SELECT workspace_id FROM core.workspaces "
                    "WHERE status='DeletionPending')"
                )
            )
            await session.execute(
                text("DELETE FROM core.workspaces WHERE status='DeletionPending'")
            )
            await session.execute(
                text(
                    "INSERT INTO auth.accounts "
                    "(account_id,status,primary_email,normalized_email) "
                    "VALUES (:a,'Active',:email,:email)"
                ),
                {"a": account_id, "email": f"purge-enq-{account_id}@test"},
            )
            await session.execute(
                text(
                    "INSERT INTO core.workspaces "
                    "(workspace_id,name,status,created_by,created_at,updated_at,"
                    "purge_eligible_at) VALUES (:w,:name,'DeletionPending',:a,now(),"
                    ":now,:now)"
                ),
                {
                    "w": workspace_id,
                    "name": f"Purge Enq {workspace_id}",
                    "a": account_id,
                    "now": datetime.now(UTC) - timedelta(days=1),
                },
            )
            await session.execute(
                text(
                    "INSERT INTO core.workspace_members "
                    "(workspace_id,account_id,membership_kind) VALUES (:w,:a,'Owner')"
                ),
                {"w": workspace_id, "a": account_id},
            )
        repository = PostgresWorkspacePurgeRepository(session, Cleanup())
        enqueuer = PostgresWorkspacePurgeEnqueuer(session, repository)
        now = datetime.now(UTC)
        assert await enqueuer.enqueue(now, 10) == 1
        assert await enqueuer.enqueue(now, 10) == 0
        count = await session.scalar(
            text(
                "SELECT count(*) FROM work.tasks "
                "WHERE task_type='lifecycle.purge.workspace' AND input_ref=:id"
            ),
            {"id": str(workspace_id)},
        )
        assert count == 1
    finally:
        await session.rollback()
        await session.close()
        await connection.close()
