"""Guarded integration: list workspaces for an account (membership authority)."""

from __future__ import annotations

import os
from pathlib import Path
from uuid import uuid4

import pytest
import pytest_asyncio
from alembic import command
from alembic.config import Config
from app_infra.postgres.engine import engine
from app_infra.postgres.permission_workspace_repository import (
    PostgresWorkspaceMembershipRepository,
)
from app_infra.postgres.test_database_guard import require_isolated_database
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


@pytest.mark.asyncio
async def test_list_workspaces_lists_owned_only() -> None:
    connection = await engine.connect()
    session = AsyncSession(connection)
    try:
        async with session.begin():
            owner = uuid4()
            other = uuid4()
            w1 = uuid4()
            w2 = uuid4()
            await session.execute(
                text(
                    "INSERT INTO auth.accounts "
                    "(account_id,status,primary_email,normalized_email) "
                    "VALUES (:a,'Active',:e,:e)"
                ),
                {"a": owner, "e": f"lst-{owner}@test"},
            )
            await session.execute(
                text(
                    "INSERT INTO auth.accounts "
                    "(account_id,status,primary_email,normalized_email) "
                    "VALUES (:a,'Active',:e,:e)"
                ),
                {"a": other, "e": f"lst-{other}@test"},
            )
            for wid, name in ((w1, "A"), (w2, "B")):
                await session.execute(
                    text(
                        "INSERT INTO core.workspaces "
                        "(workspace_id,name,status,created_by,created_at,updated_at) "
                        "VALUES (:w,:n,'Active',:a,now(),now())"
                    ),
                    {"w": wid, "n": name, "a": owner},
                )
            await session.execute(
                text(
                    "INSERT INTO core.workspace_members "
                    "(workspace_id,account_id,membership_kind) "
                    "VALUES (:w,:a,'Owner')"
                ),
                {"w": w1, "a": owner},
            )
            # other owns w2 -> should NOT appear for owner
            await session.execute(
                text(
                    "INSERT INTO core.workspace_members "
                    "(workspace_id,account_id,membership_kind) "
                    "VALUES (:w,:a,'Owner')"
                ),
                {"w": w2, "a": other},
            )
        membership = PostgresWorkspaceMembershipRepository(session)
        async with session.begin():
            rows = await membership.list_workspaces_for_account(owner)
        ids = {str(r[0]) for r in rows}
        assert str(w1) in ids
        assert str(w2) not in ids
    finally:
        await session.close()
        await connection.close()
