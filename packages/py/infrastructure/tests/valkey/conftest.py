from __future__ import annotations

from collections.abc import AsyncIterator

import pytest_asyncio
from redis.asyncio import Redis

# Dedicated Valkey database for the account/auth rate limiter and session-cache
# adapter tests. It runs against the real local Valkey service and is wiped
# before/after every test; nothing here is mocked.
VALKEY_URL = "redis://localhost:6379/14"


@pytest_asyncio.fixture
async def valkey_client() -> AsyncIterator[Redis]:
    client = Redis.from_url(VALKEY_URL, decode_responses=True)
    await client.flushdb()
    try:
        yield client
    finally:
        await client.flushdb()
        await client.aclose()
