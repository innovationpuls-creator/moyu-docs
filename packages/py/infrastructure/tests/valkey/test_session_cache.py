from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from uuid import uuid4

from app_core.session.domain.session import Session, SessionStatus
from app_core.session.ports.session_cache import SessionCachedData
from app_infra.valkey.session_cache import (
    SESSION_INVALIDATION_CHANNEL,
    ValkeySessionCache,
    session_cache_key,
)
from conftest import VALKEY_URL
from redis.asyncio import Redis


def _active_session(*, device_id: str = "device-1") -> Session:
    return Session.create(
        account_id=uuid4(),
        device_id=device_id,
        at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )


async def _await_message(pubsub, timeout: float):
    """Poll for one non-subscribe pubsub message until the deadline."""
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while loop.time() < deadline:
        message = await pubsub.get_message(ignore_subscribe_messages=True)
        if message is not None:
            return message
        await asyncio.sleep(0.05)
    return None


async def test_set_and_get_session_roundtrip(valkey_client: Redis) -> None:
    cache = ValkeySessionCache(valkey_client)
    session = _active_session()

    await cache.set_session(session)

    data = await cache.get_session(session.session_id)
    assert data is not None
    assert isinstance(data, SessionCachedData)
    assert data.session_id == session.session_id
    assert data.account_id == session.account_id
    assert data.device_id == session.device_id
    assert data.status == SessionStatus.ACTIVE
    assert data.expires_at == session.expires_at
    assert data.last_strong_auth_at == session.last_strong_auth_at


async def test_get_missing_session_returns_none(valkey_client: Redis) -> None:
    cache = ValkeySessionCache(valkey_client)
    assert await cache.get_session(uuid4()) is None


async def test_default_ttl_is_5_seconds(valkey_client: Redis) -> None:
    cache = ValkeySessionCache(valkey_client)
    session = _active_session()

    await cache.set_session(session)

    ttl_ms = await valkey_client.pttl(session_cache_key(session.session_id))
    assert 0 < ttl_ms <= 5000


async def test_custom_ttl_is_honored(valkey_client: Redis) -> None:
    cache = ValkeySessionCache(valkey_client)
    session = _active_session()

    await cache.set_session(session, ttl_seconds=60)

    ttl_ms = await valkey_client.pttl(session_cache_key(session.session_id))
    assert 59000 < ttl_ms <= 60000


async def test_entry_disappears_after_short_ttl(valkey_client: Redis) -> None:
    cache = ValkeySessionCache(valkey_client)
    session = _active_session()

    await cache.set_session(session, ttl_seconds=1)
    assert await cache.get_session(session.session_id) is not None

    for _ in range(60):  # wait up to ~3s for real TTL expiry
        await asyncio.sleep(0.05)
        if await cache.get_session(session.session_id) is None:
            break
    assert await cache.get_session(session.session_id) is None


async def test_invalidate_session_deletes_key_and_publishes(
    valkey_client: Redis,
) -> None:
    cache = ValkeySessionCache(valkey_client)
    session = _active_session()
    await cache.set_session(session)

    pubsub = valkey_client.pubsub()
    await pubsub.subscribe(SESSION_INVALIDATION_CHANNEL)
    try:
        await cache.invalidate_session(session.session_id)

        assert await cache.get_session(session.session_id) is None
        message = await _await_message(pubsub, 2.0)
        assert message is not None
        assert message["type"] == "message"
        payload = json.loads(message["data"])
        assert payload["session_id"] == str(session.session_id)
        assert payload["reason"] is None
    finally:
        await pubsub.aclose()


async def test_publish_invalidation_carries_reason(valkey_client: Redis) -> None:
    cache = ValkeySessionCache(valkey_client)
    session_id = uuid4()

    pubsub = valkey_client.pubsub()
    await pubsub.subscribe(SESSION_INVALIDATION_CHANNEL)
    try:
        await cache.publish_invalidation(session_id, "NewDeviceLogin")

        message = await _await_message(pubsub, 2.0)
        assert message is not None
        payload = json.loads(message["data"])
        assert payload["session_id"] == str(session_id)
        assert payload["reason"] == "NewDeviceLogin"
    finally:
        await pubsub.aclose()


async def test_invalidation_visible_across_clients(valkey_client: Redis) -> None:
    second_client = Redis.from_url(VALKEY_URL, decode_responses=True)
    try:
        writer = ValkeySessionCache(valkey_client)
        reader = ValkeySessionCache(second_client)
        session = _active_session()

        await writer.set_session(session)
        assert await reader.get_session(session.session_id) is not None

        await writer.invalidate_session(session.session_id)
        assert await writer.get_session(session.session_id) is None
        assert await reader.get_session(session.session_id) is None
    finally:
        await second_client.aclose()
