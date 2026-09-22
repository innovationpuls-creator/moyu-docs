from collections.abc import AsyncIterator

import pytest_asyncio
from app_infra.postgres.engine import engine
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

_TABLE = "task5_fixture_isolation_probe"
_TOKEN = "committed-row-must-be-rolled-back"


@pytest_asyncio.fixture(scope="module", autouse=True)
async def isolation_probe_table() -> AsyncIterator[None]:
    async with engine.begin() as connection:
        await connection.execute(
            text(f"CREATE TABLE IF NOT EXISTS {_TABLE} (value text NOT NULL)")
        )
        await connection.execute(text(f"TRUNCATE TABLE {_TABLE}"))
    yield
    async with engine.begin() as connection:
        await connection.execute(text(f"DROP TABLE IF EXISTS {_TABLE}"))


async def test_committed_fixture_data_is_rolled_back(clean_db: AsyncSession) -> None:
    await clean_db.execute(
        text(f"INSERT INTO {_TABLE} (value) VALUES (:value)"), {"value": _TOKEN}
    )
    await clean_db.commit()


async def test_previous_fixture_scope_does_not_leak_committed_data() -> None:
    async with engine.connect() as connection:
        result = await connection.execute(
            text(f"SELECT count(*) FROM {_TABLE} WHERE value = :value"),
            {"value": _TOKEN},
        )
        assert result.scalar_one() == 0
