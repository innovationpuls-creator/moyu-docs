from __future__ import annotations

import os
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from app_infra.postgres.test_database_guard import require_isolated_database
from sqlalchemy import inspect
from sqlalchemy.ext.asyncio import create_async_engine

DATABASE_URL = "postgresql+psycopg://torch@localhost:5432/dom_workspace_lifecycle_test"


@pytest.mark.asyncio
async def test_async_task_migration_round_trip() -> None:
    database_url = require_isolated_database(os.environ["DATABASE_URL"])
    assert database_url == DATABASE_URL
    config = Config(str(Path("migrations/postgres/alembic.ini")))
    config.set_main_option("sqlalchemy.url", database_url)
    command.upgrade(config, "head")
    engine = create_async_engine(database_url)
    try:
        async with engine.connect() as connection:
            tables = await connection.run_sync(
                lambda sync: inspect(sync).get_table_names(schema="work")
            )
        assert {"tasks", "task_attempts", "task_effects"} <= set(tables)
        command.downgrade(config, "0003")
        async with engine.connect() as connection:
            tables = await connection.run_sync(
                lambda sync: inspect(sync).get_table_names(schema="work")
            )
        assert not {"tasks", "task_attempts", "task_effects"} & set(tables)
    finally:
        await engine.dispose()
