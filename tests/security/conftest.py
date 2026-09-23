"""Shared fixtures for the Phase 9 security tests (plan Task 28).

Mirrors services/api/tests/conftest.py: the ASGI app under test runs against
the REAL local PostgreSQL (dom_dev) and the REAL local Valkey (docker
dom-valkey, db 14). The DB session is a savepoint-wrapped transaction rolled
back after every test; the Valkey database is FLUSHDB'd before and after every
test. Nothing is mocked beyond dependency overrides that point the app at
these test resources. ``db_session`` is inherited from tests/conftest.py
(identical implementation), so it is not redefined here.
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator, Callable
from pathlib import Path

import pytest_asyncio
from alembic import command
from alembic.config import Config
from redis.asyncio import Redis

os.environ.setdefault(
    "DATABASE_URL", "postgresql+psycopg://torch@localhost:5432/dom_dev"
)
os.environ.setdefault("VALKEY_URL", "redis://localhost:6379/14")

from api.dependencies.auth import (  # noqa: E402  # type: ignore[import-untyped]
    get_db_session,
    get_mailer,
    get_rate_limiter,
    get_valkey,
)
from api.main import create_app  # noqa: E402  # type: ignore[import-untyped]
from app_infra.valkey.rate_limiter import RateLimiter  # noqa: E402
from httpx import ASGITransport, AsyncClient  # noqa: E402
from sqlalchemy.ext.asyncio import AsyncSession  # noqa: E402

ALEMBIC_INI = Path("migrations/postgres/alembic.ini")

ClientFactory = Callable[..., AsyncClient]


def _alembic_config(database_url: str) -> Config:
    config = Config(str(ALEMBIC_INI))
    config.set_main_option("sqlalchemy.url", database_url)
    return config


@pytest_asyncio.fixture(scope="session")
async def migrated_database() -> None:
    """Bring dom_dev to head once per session (idempotent; mirrors
    services/api/tests/conftest.py and tests/migration/test_migration.py)."""
    database_url = os.getenv("DATABASE_URL", "postgresql+psycopg:///dom_dev")
    command.upgrade(_alembic_config(database_url), "head")


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
def client_factory(
    migrated_database: None,
    db_session: AsyncSession,
    valkey_client: Redis,
):
    """Build an ASGI httpx client with test-resource dependency overrides.

    ``rate_limiter`` injects a RateLimiter with custom windows so lockout
    self-heal can be exercised in seconds instead of 15 minutes; ``mailer``
    injects a capturing/failing mailer.
    """

    def build(
        *,
        rate_limiter: RateLimiter | None = None,
        mailer: object | None = None,
        cookies: dict[str, str] | None = None,
    ) -> AsyncClient:
        app = create_app(debug=True)
        app.dependency_overrides[get_db_session] = lambda: db_session
        app.dependency_overrides[get_valkey] = lambda: valkey_client
        if rate_limiter is not None:
            app.dependency_overrides[get_rate_limiter] = lambda: rate_limiter
        if mailer is not None:
            app.dependency_overrides[get_mailer] = lambda: mailer
        return AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
            cookies=cookies,
        )

    return build


@pytest_asyncio.fixture
async def api_client(
    client_factory: ClientFactory,
) -> AsyncIterator[AsyncClient]:
    """Default client with no extra overrides (fresh per test)."""
    client = client_factory()
    async with client as active:
        yield active
