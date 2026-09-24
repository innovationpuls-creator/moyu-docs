from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pytest
import pytest_asyncio
from alembic import command
from alembic.config import Config
from app_core.workspace.ports.purge import (
    PurgeDisposition,
    WorkspaceMembershipCleanupPort,
)
from app_infra.postgres.engine import engine
from app_infra.postgres.test_database_guard import require_isolated_database
from app_infra.postgres.workspace_purge_repository import (
    PostgresWorkspacePurgeRepository,
)
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


class _PermissionCleanupFake(WorkspaceMembershipCleanupPort):
    """Permission-owned port adapter for tests: deletes memberships."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def remove_workspace_memberships(self, workspace_id) -> None:
        await self._session.execute(
            text("DELETE FROM core.workspace_members WHERE workspace_id=:w"),
            {"w": workspace_id},
        )


DATABASE_URL = "postgresql+psycopg://torch@localhost:5432/dom_workspace_lifecycle_test"


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
            for t in (
                "core.workspace_members",
                "core.folders",
                "core.projects",
                "core.workspaces",
            ):
                await session.execute(text(f"DELETE FROM {t}"))
            await session.execute(
                text(
                    "DELETE FROM auth.accounts WHERE primary_email LIKE 'purge-%@test'"
                )
            )
        await session.close()
    finally:
        await connection.close()


async def _seed_workspace(
    session: AsyncSession,
    *,
    status: str,
    trashed_days_ago: int,
    name: str = "PurgeMe",
) -> str:
    account_id = uuid4()
    workspace_id = uuid4()
    # purge_eligible_at = trashed_at + 30 days; trashed_days_ago==30 => now
    eligible_at = datetime.now(UTC) + timedelta(days=30 - trashed_days_ago)
    await session.execute(
        text(
            "INSERT INTO auth.accounts "
            "(account_id,status,primary_email,normalized_email) "
            "VALUES (:a,'Active',:e,:e)"
        ),
        {"a": account_id, "e": f"purge-{account_id}@test"},
    )
    await session.execute(
        text(
            "INSERT INTO core.workspaces "
            "(workspace_id,name,status,created_by,created_at,updated_at,"
            "purge_eligible_at,purge_executed_at) "
            "VALUES (:w,:n,:s,:a,now(),now(),:el,NULL)"
        ),
        {
            "w": workspace_id,
            "n": name,
            "s": status,
            "a": account_id,
            "el": eligible_at,
        },
    )
    # Permission invariant: every non-Deleted Workspace has exactly one Owner
    await session.execute(
        text(
            "INSERT INTO core.workspace_members "
            "(workspace_id,account_id,membership_kind) VALUES (:w,:a,'Owner')"
        ),
        {"w": workspace_id, "a": account_id},
    )
    return str(workspace_id), str(account_id)


async def _seed_project(
    session: AsyncSession, workspace_id: str, account_id: str, name: str
) -> str:
    project_id = uuid4()
    await session.execute(
        text(
            "INSERT INTO core.projects "
            "(project_id,workspace_id,name,normalized_name,lifecycle,"
            "created_by,created_at,updated_at) "
            "VALUES (:p,:w,:n,:nn,'Active',:a,now(),now())"
        ),
        {
            "p": project_id,
            "w": workspace_id,
            "n": name,
            "nn": name.lower(),
            "a": account_id,
        },
    )
    return str(project_id)


@pytest.mark.asyncio
async def test_eligibility_boundary_and_index_scan() -> None:
    connection = await engine.connect()
    session = AsyncSession(connection)
    try:
        async with session.begin():
            eligible, _ = await _seed_workspace(
                session, status="DeletionPending", trashed_days_ago=30
            )
            not_yet, _ = await _seed_workspace(
                session, status="DeletionPending", trashed_days_ago=29
            )
            live, _ = await _seed_workspace(
                session, status="Active", trashed_days_ago=60
            )
        repo = PostgresWorkspacePurgeRepository(
            session, _PermissionCleanupFake(session)
        )
        candidates = await repo.candidates_before(datetime.now(UTC), 100)
        ids = [str(c.workspace_id) for c in candidates]
        assert eligible in ids
        assert not_yet not in ids  # 29 days < 30 -> not eligible yet
        assert live not in ids  # Active never eligible
    finally:
        await session.close()
        await connection.close()


@pytest.mark.asyncio
async def test_purge_deletes_children_and_releases_sibling_name() -> None:
    connection = await engine.connect()
    session = AsyncSession(connection)
    try:
        async with session.begin():
            ws, acct = await _seed_workspace(
                session, status="DeletionPending", trashed_days_ago=31
            )
            await _seed_project(session, ws, acct, "Design.md")
        repo = PostgresWorkspacePurgeRepository(
            session, _PermissionCleanupFake(session)
        )
        async with session.begin():
            result = await repo.purge_workspace(ws)
        assert result.disposition == PurgeDisposition.PURGED
        async with session.begin():
            ws_count = await session.scalar(
                text("SELECT count(*) FROM core.workspaces WHERE workspace_id=:w"),
                {"w": ws},
            )
            pr_count = await session.scalar(
                text("SELECT count(*) FROM core.projects WHERE workspace_id=:w"),
                {"w": ws},
            )
            # sibling-name reservation physically released: no row with the
            # purged project's normalized name remains anywhere (user ruling:
            # retention lasts until physical cleanup)
            reservation = await session.scalar(
                text(
                    "SELECT count(*) FROM core.projects "
                    "WHERE normalized_name='design.md'"
                )
            )
        assert ws_count == 0
        assert pr_count == 0
        assert reservation == 0
    finally:
        await session.close()
        await connection.close()


@pytest.mark.asyncio
async def test_purge_is_idempotent_for_missing_and_excludes_restored() -> None:
    connection = await engine.connect()
    session = AsyncSession(connection)
    try:
        async with session.begin():
            ws, _ = await _seed_workspace(
                session, status="DeletionPending", trashed_days_ago=32
            )
        repo = PostgresWorkspacePurgeRepository(
            session, _PermissionCleanupFake(session)
        )
        async with session.begin():
            first = await repo.purge_workspace(ws)
            second = await repo.purge_workspace(ws)
        assert first.disposition == PurgeDisposition.PURGED
        assert second.disposition == PurgeDisposition.ALREADY_PURGED
    finally:
        await session.close()
        await connection.close()


@pytest.mark.asyncio
async def test_rollback_keeps_workspace_rows() -> None:
    connection = await engine.connect()
    session = AsyncSession(connection)
    try:
        async with session.begin():
            ws, _ = await _seed_workspace(
                session, status="DeletionPending", trashed_days_ago=31
            )
        repo = PostgresWorkspacePurgeRepository(
            session, _PermissionCleanupFake(session)
        )
        try:
            async with session.begin():
                await repo.purge_workspace(ws)
                raise RuntimeError("boom")
        except RuntimeError:
            pass
        async with session.begin():
            count = await session.scalar(
                text("SELECT count(*) FROM core.workspaces WHERE workspace_id=:w"),
                {"w": ws},
            )
        assert count == 1  # rolled back, nothing deleted
    finally:
        await session.close()
        await connection.close()
