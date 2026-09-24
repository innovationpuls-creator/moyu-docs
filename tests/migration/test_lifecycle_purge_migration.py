"""Guarded migration 0005 (Lifecycle Purge) tests.

Runs against the disposable isolated dom_workspace_lifecycle_test database
only; refuses any other target. Never touches dom_dev/mutiagent.
"""

import os
from pathlib import Path
from urllib.parse import urlparse

import pytest
from alembic import command
from alembic.config import Config
from app_infra.postgres.engine import engine
from sqlalchemy import text

DATABASE_URL = "postgresql+psycopg://torch@localhost:5432/dom_workspace_lifecycle_test"


def _guard() -> str:
    value = os.environ.get("DATABASE_URL")
    if value is None:
        pytest.fail("DATABASE_URL must explicitly target the isolated migration DB")
    if urlparse(value).path.lstrip("/") != "dom_workspace_lifecycle_test":
        pytest.fail("DATABASE_URL must target dom_workspace_lifecycle_test")
    return value


def _alembic_config(database_url: str) -> Config:
    config = Config(str(Path("migrations/postgres/alembic.ini")))
    config.set_main_option("sqlalchemy.url", database_url)
    return config


def test_lifecycle_purge_migration_upgrade_downgrade_round_trip() -> None:
    database_url = _guard()
    assert database_url == DATABASE_URL
    config = _alembic_config(database_url)
    command.upgrade(config, "0005")
    command.downgrade(config, "0004")
    command.upgrade(config, "head")
    assert True


def test_lifecycle_purge_migration_adds_columns_and_index() -> None:
    import asyncio

    from sqlalchemy.ext.asyncio import AsyncSession

    database_url = _guard()
    assert database_url == DATABASE_URL
    config = _alembic_config(database_url)
    command.upgrade(config, "head")

    async def _check() -> None:
        session = AsyncSession(engine)
        try:
            async with session.begin():
                columns = [
                    r[0]
                    for r in (
                        await session.execute(
                            text(
                                "SELECT column_name FROM information_schema.columns "
                                "WHERE table_schema='core' AND table_name='workspaces' "
                                "AND column_name IN "
                                "('purge_eligible_at','purge_executed_at')"
                            )
                        )
                    ).all()
                ]
                index = await session.scalar(
                    text(
                        "SELECT count(*) FROM pg_indexes WHERE schemaname='core' "
                        "AND tablename='workspaces' "
                        "AND indexname LIKE '%purge%'"
                    )
                )
        finally:
            await session.close()
        assert set(columns) == {"purge_eligible_at", "purge_executed_at"}
        assert index and index > 0

    asyncio.run(_check())
