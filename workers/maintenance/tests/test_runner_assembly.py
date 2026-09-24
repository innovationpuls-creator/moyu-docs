"""Arch 25: the maintenance runner assembles consumers over the real chain."""

from __future__ import annotations

from collections.abc import AsyncGenerator
from uuid import uuid4

import pytest
import pytest_asyncio
from alembic import command
from alembic.config import Config
from app_infra.postgres.engine import engine
from app_infra.postgres.resource.journal_repository import PostgresJournalRepository
from app_infra.postgres.resource.resource_repository import (
    PostgresResourceRepository,
)
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from workers.maintenance.main import build_registry, sweep

DATABASE_URL = "postgresql+psycopg://torch@localhost:5432/dom_workspace_lifecycle_test"


@pytest_asyncio.fixture(scope="module", autouse=True)
async def migrated_database() -> None:
    config = Config(str("migrations/postgres/alembic.ini"))
    config.set_main_option("sqlalchemy.url", DATABASE_URL)
    command.upgrade(config, "head")


@pytest_asyncio.fixture
async def db_session() -> AsyncGenerator[AsyncSession, None]:
    conn = await engine.connect()
    tx = await conn.begin()
    factory = async_sessionmaker(bind=conn, expire_on_commit=False, class_=AsyncSession)
    session = factory()
    try:
        yield session
    finally:
        await session.close()
        await tx.rollback()
        await conn.close()


@pytest.mark.asyncio
async def test_runner_assembles_consumers_and_sweeps(db_session: AsyncSession) -> None:
    """The runner wires the real consumers + enqueuers over the chain; the
    claim/checkpoint EXECUTION is proven by the consumer BDDs."""
    registry = build_registry(db_session)
    for task_type in ("resource.checkpoint", "resource.purge", "lifecycle.purge"):
        assert task_type in registry, task_type
    assert "webhook.deliver" in registry
    async with db_session.begin():
        account_id = uuid4()
        workspace_id = uuid4()
        project_id = uuid4()
        await db_session.execute(
            text(
                "INSERT INTO auth.accounts "
                "(account_id,status,primary_email,normalized_email) "
                "VALUES (:a,'Active',:e,:e)"
            ),
            {"a": account_id, "e": f"runa-{account_id}@test"},
        )
        await db_session.execute(
            text(
                "INSERT INTO core.workspaces "
                "(workspace_id,name,status,created_by,created_at,updated_at) "
                "VALUES (:w,'W','Active',:a,now(),now())"
            ),
            {"w": workspace_id, "a": account_id},
        )
        await db_session.execute(
            text(
                "INSERT INTO core.workspace_members "
                "(workspace_id,account_id,membership_kind) "
                "VALUES (:w,:a,'Owner')"
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
        await PostgresJournalRepository(db_session).append_op(
            resource.resource_id, 1, 1, b"op", "h"
        )
    enqueued = await sweep(db_session)
    assert enqueued >= 1  # global sweep; other tests may also qualify


@pytest.mark.asyncio
async def test_daemon_ticks_bound(db_session: AsyncSession) -> None:
    """The daemon loop performs a bounded number of claim cycles (max_ticks)."""
    from workers.maintenance.main import run_daemon

    worked = await run_daemon(db_session, max_ticks=2)
    assert worked <= 2
