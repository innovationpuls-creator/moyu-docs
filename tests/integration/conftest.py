"""Shared fixtures for the Phase 9 integration tests (plan Task 28).

The concurrency / convergence / registration-race tests need REAL committed
transactions (unlike the savepoint-rolled-back db_session in tests/conftest.py
which is preserved for the existing integration tests). This conftest adds:

- ``migrated_database``: dom_dev brought to head once per session.
- ``valkey_client``: real local Valkey (dom-valkey, db 14), flushed
  before and after every test.
- ``cleanup_accounts``: records committed test emails and removes every row
  the test created (audit, outbox, then the account — cascading to sessions /
  identities / credentials / tokens) after the test, so no committed fixture
  data leaks between tests.
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import pytest_asyncio
from alembic import command
from alembic.config import Config
from redis.asyncio import Redis
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

os.environ.setdefault(
    "DATABASE_URL", "postgresql+psycopg://torch@localhost:5432/dom_dev"
)
_configured_valkey_url = os.environ.get("VALKEY_URL", "redis://localhost:6379/14")
_valkey_url_parts = urlsplit(_configured_valkey_url)
if not _valkey_url_parts.scheme or not _valkey_url_parts.netloc:
    raise ValueError("VALKEY_URL must be an absolute Redis URL")
_valkey_query = [
    (key, value)
    for key, value in parse_qsl(_valkey_url_parts.query, keep_blank_values=True)
    if key.casefold() != "db"
]
_valkey_query.append(("db", "14"))
os.environ["VALKEY_URL"] = urlunsplit(
    _valkey_url_parts._replace(path="/14", query=urlencode(_valkey_query))
)

from app_infra.postgres.engine import engine  # noqa: E402

ALEMBIC_INI = Path("migrations/postgres/alembic.ini")


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


async def _delete_account_committed_rows(
    connection: AsyncConnection, email: str
) -> None:
    """Remove every committed row an integration test created for one email.

    Order matters: audit.entries and integration.outbox_events have no FK to
    auth.accounts, so they are deleted first; deleting the account cascades to
    sessions, identities, password_credentials and one_time_tokens (migration
    0001, ondelete=CASCADE).
    """
    account_id = await connection.scalar(
        text("SELECT account_id FROM auth.accounts WHERE normalized_email = :e"),
        {"e": email.strip().casefold()},
    )
    if account_id is None:
        return
    await connection.execute(
        text("DELETE FROM audit.entries WHERE actor_id = :account_id"),
        {"account_id": account_id},
    )
    await connection.execute(
        text(
            "DELETE FROM integration.outbox_events WHERE aggregate_id IN "
            "(SELECT session_id FROM auth.sessions WHERE account_id = :account_id) "
            "OR aggregate_id = :account_id"
        ),
        {"account_id": account_id},
    )
    await connection.execute(
        text("DELETE FROM auth.accounts WHERE account_id = :account_id"),
        {"account_id": account_id},
    )


@pytest_asyncio.fixture
async def cleanup_accounts() -> AsyncIterator[list[str]]:
    """Record committed test emails; remove their rows after the test."""
    created: list[str] = []
    yield created
    async with engine.begin() as connection:
        for email in set(created):
            await _delete_account_committed_rows(connection, email)
