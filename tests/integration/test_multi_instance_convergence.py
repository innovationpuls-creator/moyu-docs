"""Phase 9 Task 28: cross-instance session-cache convergence <= 5s.

Review Focus #3 / FR-AUTH-015 + PRD cross-requirement invariant 2: after
instance A invalidates a session, every other instance must stop seeing it as
valid within 5 seconds. The shared Valkey makes the DELETE instantly visible
to all instances; the 5s default TTL bounds staleness even when an
invalidation event is delayed; the ``events:session_invalidated`` pubsub
channel notifies any instance holding a local mirror (the realtime service's
session_invalidator.ts consumes the same channel, plan Task 26).

Tests run against the REAL local Valkey (db 14) with two independent client
connections standing in for two service instances, plus one end-to-end login
-> cache bound -> logout assertion through the API app.
"""

from __future__ import annotations

import asyncio
import json
import os
import time
from datetime import datetime, timezone
from uuid import UUID, uuid4

from api.dependencies.auth import get_db_session, get_valkey
from api.main import create_app
from app_core.session.domain.session import Session
from app_infra.valkey.session_cache import (
    SESSION_INVALIDATION_CHANNEL,
    ValkeySessionCache,
    session_cache_key,
)
from httpx import ASGITransport, AsyncClient
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

VALID_PASSWORD = "Str0ng#Passw0rd"
VALKEY_URL = os.environ.get("VALKEY_URL", "redis://localhost:6379/14")


def _fresh_client() -> Redis:
    return Redis.from_url(VALKEY_URL, decode_responses=True)


async def test_invalidation_propagates_across_instances_within_five_seconds(
    valkey_client: Redis,
) -> None:
    cache_a = ValkeySessionCache(valkey_client)
    second_instance = _fresh_client()
    try:
        cache_b = ValkeySessionCache(second_instance)
        session = Session.create(
            account_id=uuid4(),
            device_id="device-x",
            at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        )

        await cache_a.set_session(session)
        # The 5s default TTL bound (FR-AUTH-015 <=5s cross-instance).
        ttl_ms = await valkey_client.pttl(session_cache_key(session.session_id))
        assert 0 < ttl_ms <= 5000

        # Instance B (a different Valkey connection) sees the cached session.
        assert await cache_b.get_session(session.session_id) is not None

        started = time.perf_counter()
        await cache_a.invalidate_session(session.session_id)
        while await cache_b.get_session(session.session_id) is not None:
            await asyncio.sleep(0.01)
            assert time.perf_counter() - started < 5.0, (
                "invalidation did not converge within the 5s bound"
            )
        elapsed = time.perf_counter() - started
        assert elapsed < 5.0

        assert await cache_a.get_session(session.session_id) is None
        assert await cache_b.get_session(session.session_id) is None
    finally:
        await second_instance.aclose()


async def _await_message(pubsub, timeout: float = 2.0) -> dict | None:
    """Poll for the next non-subscribe pubsub message until the deadline.

    redis.asyncio's ``get_message(timeout=...)`` does not reliably surface a
    buffered message, so we poll the non-blocking variant (same pattern as
    packages/py/infrastructure/tests/valkey).
    """
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while loop.time() < deadline:
        message = await pubsub.get_message(ignore_subscribe_messages=True)
        if message is not None:
            return message
        await asyncio.sleep(0.02)
    return None


async def test_invalidation_event_reaches_pubsub_subscribers(
    valkey_client: Redis,
) -> None:
    cache = ValkeySessionCache(valkey_client)
    second_instance = _fresh_client()
    try:
        pubsub = second_instance.pubsub()
        await pubsub.subscribe(SESSION_INVALIDATION_CHANNEL)
        try:
            session_id = uuid4()
            await cache.publish_invalidation(session_id, "NewDeviceLogin")
            message = await _await_message(pubsub)
            assert message is not None
            payload = json.loads(message["data"])
            assert payload["session_id"] == str(session_id)
            assert payload["reason"] == "NewDeviceLogin"

            other = uuid4()
            await cache.invalidate_session(other)
            message = await _await_message(pubsub)
            assert message is not None
            payload = json.loads(message["data"])
            assert payload["session_id"] == str(other)
            assert payload["reason"] is None
        finally:
            await pubsub.aclose()
    finally:
        await second_instance.aclose()


async def test_login_sets_default_five_second_cache_ttl_and_logout_invalidates(
    db_session: AsyncSession,
    valkey_client: Redis,
) -> None:
    """End-to-end: a real login caches the new session with the 5s default
    bound; logout invalidates it, so a stale credential is gone immediately
    (the fast-path check in get_current_session sees a cache miss)."""
    app = create_app(debug=True)
    app.dependency_overrides[get_db_session] = lambda: db_session
    app.dependency_overrides[get_valkey] = lambda: valkey_client
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        email = f"convergence-{uuid4().hex[:12]}@example.com"
        register = await client.post(
            "/v1/auth/register", json={"email": email, "password": VALID_PASSWORD}
        )
        assert register.status_code == 201

        login = await client.post(
            "/v1/auth/login", json={"email": email, "password": VALID_PASSWORD}
        )
        assert login.status_code == 200
        session_id = UUID(_session_cookie_value(login.headers))
        assert session_id

        # The login route caches the new session with the default 5s TTL
        # (FR-AUTH-015 bound for the fast path; the cache is disposable and
        # Postgres stays authoritative, doc 16 §125).
        ttl_ms = await valkey_client.pttl(session_cache_key(session_id))
        assert 0 < ttl_ms <= 5000

        logged_out = await client.post("/v1/auth/logout")
        assert logged_out.status_code == 200
        # logout invalidates the cached entry -> stale credential gone now.
        assert await valkey_client.get(session_cache_key(session_id)) is None


def _session_cookie_value(headers) -> str:
    for line in headers.get_list("set-cookie"):
        if line.split("=", 1)[0].strip() == "dom_session":
            return line.split("=", 1)[1].split(";", 1)[0].strip()
    return ""
