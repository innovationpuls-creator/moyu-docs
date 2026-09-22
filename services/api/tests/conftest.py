"""Shared fixtures for the DOM API service tests (plan Task 20/21).

The API under test runs against the REAL local PostgreSQL (dom_dev) and the
REAL local Valkey (docker dom-valkey, db 14), mirroring the infrastructure
adapter test pattern (packages/py/infrastructure/tests): the DB session is a
savepoint-wrapped transaction that rolls back after every test, and the Valkey
database is FLUSHDB'd before and after every test. Nothing here is mocked
beyond dependency overrides that point the app at these test resources.
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from pathlib import Path

import pytest_asyncio
from alembic import command
from alembic.config import Config
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

os.environ.setdefault(
    "DATABASE_URL", "postgresql+psycopg://torch@localhost:5432/dom_dev"
)
os.environ.setdefault("VALKEY_URL", "redis://localhost:6379/14")

# Imported after the env defaults above so app_infra.postgres.engine reads the
# intended DATABASE_URL.
from api.dependencies.auth import (  # noqa: E402
    get_db_session,
    get_mailer,
    get_valkey,
)
from api.mailer import LoggingMailer  # noqa: E402
from api.main import create_app  # noqa: E402
from app_infra.postgres.engine import engine  # noqa: E402
from httpx import ASGITransport, AsyncClient  # noqa: E402

ALEMBIC_INI = Path("migrations/postgres/alembic.ini")


def _alembic_config(database_url: str) -> Config:
    config = Config(str(ALEMBIC_INI))
    config.set_main_option("sqlalchemy.url", database_url)
    return config


@pytest_asyncio.fixture(scope="session")
async def migrated_database() -> None:
    """Bring dom_dev to head once per session (idempotent; mirrors
    tests/migration/test_migration.py) so services/api tests are
    self-sufficient even when run before the migration suite."""
    database_url = os.getenv("DATABASE_URL", "postgresql+psycopg:///dom_dev")
    command.upgrade(_alembic_config(database_url), "head")


@pytest_asyncio.fixture
async def db_session() -> AsyncIterator[AsyncSession]:
    async with engine.connect() as connection:
        transaction = await connection.begin()
        factory = async_sessionmaker(
            bind=connection,
            expire_on_commit=False,
            class_=AsyncSession,
            join_transaction_mode="create_savepoint",
        )
        async with factory() as session:
            try:
                yield session
            finally:
                await session.rollback()
                await transaction.rollback()


@pytest_asyncio.fixture
async def valkey_client() -> AsyncIterator[Redis]:
    client = Redis.from_url(os.environ["VALKEY_URL"], decode_responses=True)
    await client.flushdb()
    try:
        yield client
    finally:
        await client.flushdb()
        await client.aclose()


@pytest_asyncio.fixture
async def api_client(
    migrated_database: None,
    db_session: AsyncSession,
    valkey_client: Redis,
) -> AsyncIterator[AsyncClient]:
    """httpx client against the create_app() ASGI app with dependency
    overrides pointing the DB session and Valkey at the test resources."""
    app = create_app(debug=True)
    app.dependency_overrides[get_db_session] = lambda: db_session
    app.dependency_overrides[get_valkey] = lambda: valkey_client
    app.dependency_overrides[get_mailer] = lambda: LoggingMailer()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client
