from __future__ import annotations

import os
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest
import pytest_asyncio
from alembic import command
from alembic.config import Config
from app_core.permission.application.workspace_ownership import (
    GrantInitialWorkspaceOwner,
)
from app_infra.postgres.engine import engine
from app_infra.postgres.test_database_guard import require_isolated_database
from app_infra.postgres.workspace_composition import build_create_workspace_use_case
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

DATABASE_URL = "postgresql+psycopg://torch@localhost:5432/dom_workspace_lifecycle_test"


@pytest_asyncio.fixture(scope="module", autouse=True)
async def migrated_database() -> None:
    database_url = require_isolated_database(os.environ["DATABASE_URL"])
    assert database_url == DATABASE_URL
    config = Config(str(Path("migrations/postgres/alembic.ini")))
    config.set_main_option("sqlalchemy.url", database_url)
    command.upgrade(config, "head")


class _FailingGrantAfterOwner(GrantInitialWorkspaceOwner):
    """Real grant that succeeds, then raises: simulates a post-grant failure in
    the shared transaction (e.g. event publish), proving full rollback."""

    async def execute(self, workspace_id, actor_id) -> None:
        await super().execute(workspace_id, actor_id)
        raise RuntimeError("simulated post-grant failure")


async def _workspace_row_count(session: AsyncSession, workspace_id) -> int:
    return (
        await session.scalar(
            text("SELECT count(*) FROM core.workspaces WHERE workspace_id=:id"),
            {"id": workspace_id},
        )
    ) or 0


@pytest.mark.asyncio
async def test_create_workspace_rolls_back_shared_transaction() -> None:
    account_id = uuid4()
    connection = await engine.connect()
    session = AsyncSession(connection)
    try:
        key = f"atomic-create-{uuid4()}"
        with pytest.raises(RuntimeError, match="post-grant failure"):
            async with session.begin():
                await session.execute(
                    text(
                        "INSERT INTO auth.accounts "
                        "(account_id, status, primary_email, normalized_email) "
                        "VALUES (:id, 'Active', :email, :email)"
                    ),
                    {"id": account_id, "email": f"{account_id}@example.test"},
                )
                use_case = build_create_workspace_use_case(
                    session, now=lambda: datetime(2026, 9, 24, tzinfo=UTC)
                )
                use_case._initial_owner = _FailingGrantAfterOwner(
                    use_case._initial_owner.memberships
                )
                await use_case.execute(account_id, "Atomic", idempotency_key=key)
        # Transaction rolled back: nothing durable.
        async with session.begin():
            workspace_count = await session.scalar(
                text("SELECT count(*) FROM core.workspaces WHERE created_by=:a"),
                {"a": account_id},
            )
            member_count = await session.scalar(
                text("SELECT count(*) FROM core.workspace_members WHERE account_id=:a"),
                {"a": account_id},
            )
            idem_count = await session.scalar(
                text(
                    "SELECT count(*) FROM integration.idempotency_records "
                    "WHERE idempotency_key LIKE :prefix"
                ),
                {"prefix": f"workspace:create:{key}"},
            )
            outbox_count = await session.scalar(
                text(
                    "SELECT count(*) FROM integration.outbox_events "
                    "WHERE aggregate_id IN ("
                    "SELECT workspace_id FROM core.workspaces WHERE created_by=:a)"
                ),
                {"a": account_id},
            )
        assert workspace_count == 0
        assert member_count == 0
        assert idem_count == 0
        assert outbox_count == 0
    finally:
        await session.close()
        await connection.close()
