"""Phase 9 Task 28: progressive login rate limiting & 15-minute lockout.

Review Focus #5 / FR-AUTH-035 (AC-035.1, AC-035.3):

- 5 consecutive failed logins -> temporary 15-minute lockout (429
  RATE_LIMITED, retryable), never a permanent lock.
- the lockout self-heals after the window (parameterized RateLimiter windows
  keep the tests seconds-fast; the default window is asserted at the adapter
  level via the real key TTL).
- a successful login clears the failure counter (progressive, not cumulative).

API-level tests exercise the real login route through the ASGI app (real
Postgres + real Valkey); adapter-level tests exercise the RateLimiter against
the real Valkey directly.
"""

from __future__ import annotations

import asyncio

import pytest
from app_core.common.exceptions import RateLimitError
from app_infra.valkey.rate_limiter import (
    LOGIN_MAX_FAILURES,
    RateLimiter,
    login_rate_key,
)
from httpx import AsyncClient, Response
from redis.asyncio import Redis

VALID_PASSWORD = "Str0ng#Passw0rd"


async def _register(client: AsyncClient, email: str) -> None:
    response = await client.post(
        "/v1/auth/register", json={"email": email, "password": VALID_PASSWORD}
    )
    assert response.status_code == 201


async def _login(
    client: AsyncClient, email: str, password: str = "Wrong!Password"
) -> Response:
    return await client.post(
        "/v1/auth/login", json={"email": email, "password": password}
    )


async def test_api_five_failed_logins_lock_out_then_self_heal(
    client_factory,
    valkey_client: Redis,
) -> None:
    """AC-035.1 + AC-035.3: 5 failures -> 429; after the (parameterized) 1s
    window the account recovers and a correct login succeeds."""
    limiter = RateLimiter(valkey_client, login_lockout_seconds=1)
    async with client_factory(rate_limiter=limiter) as client:
        await _register(client, "lockout-selfheal@example.com")

        statuses = [
            (await _login(client, "lockout-selfheal@example.com")).status_code
            for _ in range(5)
        ]
        assert statuses == [401, 401, 401, 401, 401]

        locked = await _login(client, "lockout-selfheal@example.com", VALID_PASSWORD)
        assert locked.status_code == 429
        body = locked.json()
        assert body["category"] == "RateLimit"
        assert body["errorCode"] == "RATE_LIMITED"
        assert body["retryable"] is True

        # Self-heal: after the 1s lockout window the key expired on Valkey.
        await asyncio.sleep(1.2)
        recovered = await _login(client, "lockout-selfheal@example.com", VALID_PASSWORD)
        assert recovered.status_code == 200


async def test_api_successful_login_clears_failure_counter(
    client_factory,
) -> None:
    """AC-035.3: a successful login resets the counter, so the next failures
    are progressive again instead of an instant lockout."""
    async with client_factory() as client:
        await _register(client, "lockout-clearon-success@example.com")

        for _ in range(3):
            assert (
                await _login(client, "lockout-clearon-success@example.com")
            ).status_code == 401
        success = await _login(
            client, "lockout-clearon-success@example.com", VALID_PASSWORD
        )
        assert success.status_code == 200  # route clears login failures

        # Counter restarted at 0: five more failures are all plain 401s; only
        # the 6th attempt observes the newly-accumulated lockout.
        statuses = [
            (await _login(client, "lockout-clearon-success@example.com")).status_code
            for _ in range(5)
        ]
        assert statuses == [401, 401, 401, 401, 401]
        locked = await _login(
            client, "lockout-clearon-success@example.com", VALID_PASSWORD
        )
        assert locked.status_code == 429


async def test_adapter_lockout_15_minute_default_window(
    valkey_client: Redis,
) -> None:
    """FR-AUTH-035: the default lockout window is 15 minutes (temporary)."""
    limiter = RateLimiter(valkey_client)
    identifier = "ip:192.168.1.1:login"

    for _ in range(LOGIN_MAX_FAILURES):
        await limiter.record_login_failure(identifier)
    with pytest.raises(RateLimitError) as excinfo:
        await limiter.check_login_rate(identifier)
    assert excinfo.value.error_code == "RATE_LIMITED"
    assert "15 分钟" in excinfo.value.message

    ttl = await valkey_client.ttl(login_rate_key(identifier))
    assert 870 <= ttl <= 900  # 15-minute temporary lockout window


async def test_adapter_lockout_self_heals_with_parameterized_window(
    valkey_client: Redis,
) -> None:
    limiter = RateLimiter(valkey_client, login_lockout_seconds=1)
    identifier = "ip:10.0.0.7:login"

    for _ in range(LOGIN_MAX_FAILURES):
        await limiter.record_login_failure(identifier)
    with pytest.raises(RateLimitError):
        await limiter.check_login_rate(identifier)

    await asyncio.sleep(1.1)  # real TTL expiry on Valkey
    await limiter.check_login_rate(identifier)  # recovered, never permanently locked


async def test_adapter_success_clears_failure_counter(valkey_client: Redis) -> None:
    limiter = RateLimiter(valkey_client)
    identifier = "ip:198.51.100.4:login"

    for _ in range(3):
        await limiter.record_login_failure(identifier)
    await limiter.clear_login_failure(identifier)  # success path

    for _ in range(LOGIN_MAX_FAILURES - 1):
        await limiter.record_login_failure(identifier)
        await limiter.check_login_rate(identifier)  # counter restarted at zero
    await limiter.record_login_failure(identifier)
    with pytest.raises(RateLimitError):
        await limiter.check_login_rate(identifier)
