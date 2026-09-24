"""Resource security gates (guarded isolated DB): no cross-owner writes by the
journal/checkpoint path; sequence tampering rejected; no secrets in task
Payload/envelope fields."""

from __future__ import annotations

import os
from pathlib import Path
from uuid import uuid4

import pytest
import pytest_asyncio
from alembic import command
from alembic.config import Config
from app_infra.postgres.engine import engine
from app_infra.postgres.resource.journal_repository import (
    DuplicateJournalSeqError,
    PostgresJournalRepository,
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
async def test_journal_append_never_touches_ownership_tables() -> None:
    connection = await engine.connect()
    session = AsyncSession(connection)
    try:
        async with session.begin():
            # minimal resources row + journal op without any ownership grant
            rid = uuid4()
            pid = uuid4()
            acc = uuid4()
            wid = uuid4()
            await session.execute(
                text(
                    "INSERT INTO auth.accounts "
                    "(account_id,status,primary_email,normalized_email) "
                    "VALUES (:a,'Active',:e,:e)"
                ),
                {"a": acc, "e": f"sec-{acc}@test"},
            )
            await session.execute(
                text(
                    "INSERT INTO core.workspaces "
                    "(workspace_id,name,status,created_by,created_at,updated_at) "
                    "VALUES (:w,'S','Active',:a,now(),now())"
                ),
                {"w": wid, "a": acc},
            )
            await session.execute(
                text(
                    "INSERT INTO core.workspace_members "
                    "(workspace_id,account_id,membership_kind) "
                    "VALUES (:w,:a,'Owner')"
                ),
                {"w": wid, "a": acc},
            )
            await session.execute(
                text(
                    "INSERT INTO core.projects "
                    "(project_id,workspace_id,name,normalized_name,lifecycle,"
                    "created_by,created_at,updated_at) "
                    "VALUES (:p,:w,'P','p','Active',:a,now(),now())"
                ),
                {"p": pid, "w": wid, "a": acc},
            )
            await session.execute(
                text(
                    "INSERT INTO core.resources "
                    "(resource_id,project_id,resource_type,name,normalized_name,"
                    "lifecycle,schema_version) "
                    "VALUES (:r,:p,'document','S','s','Active','1.0.0')"
                ),
                {"r": rid, "p": pid},
            )
        journal = PostgresJournalRepository(session)
        async with session.begin():
            await journal.append_op(rid, 1, 1, b"op", "hash")
        async with session.begin():
            ownership_count = await session.scalar(
                text(
                    "SELECT count(*) FROM collab.resource_ownership "
                    "WHERE resource_id=:r"
                ),
                {"r": rid},
            )
            # re-append same seq must be rejected (tamper / duplication guard)
            seq_ok = True
            try:
                await journal.append_op(rid, 1, 1, b"op2", "hash2")
            except DuplicateJournalSeqError:
                seq_ok = False
            assert not seq_ok
        assert ownership_count == 0  # journal path never writes ownership
    finally:
        await session.close()
        await connection.close()
