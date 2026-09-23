from __future__ import annotations

import asyncio
from uuid import uuid4

import pytest
from app_core.common.exceptions import RateLimitError
from app_infra.valkey.rate_limiter import (
    LOGIN_MAX_FAILURES,
    REGISTER_MAX_ATTEMPTS,
    RateLimiter,
    login_rate_key,
    register_rate_key,
    verify_email_count_key,
    verify_email_last_sent_key,
)
from redis.asyncio import Redis


async def test_progressive_lockout_after_five_failures(
    valkey_client: Redis,
) -> None:
    limiter = RateLimiter(valkey_client)
    identifier = "ip:192.168.1.1:login"

    for _ in range(LOGIN_MAX_FAILURES - 1):
        await limiter.record_login_failure(identifier)
        await limiter.check_login_rate(identifier)  # still allowed below threshold

    await limiter.record_login_failure(identifier)  # 5th failure
    with pytest.raises(RateLimitError) as excinfo:
        await limiter.check_login_rate(identifier)
    assert excinfo.value.error_code == "RATE_LIMITED"
    assert excinfo.value.category == "RateLimit"
    assert "15 分钟" in excinfo.value.message


async def test_lockout_window_is_15_minutes_by_default(
    valkey_client: Redis,
) -> None:
    limiter = RateLimiter(valkey_client)
    identifier = "email:attacker@example.com"
    for _ in range(LOGIN_MAX_FAILURES):
        await limiter.record_login_failure(identifier)

    ttl = await valkey_client.ttl(login_rate_key(identifier))
    assert 870 <= ttl <= 900  # 15-minute temporary lockout window


async def test_lockout_is_temporary_and_expires(valkey_client: Redis) -> None:
    limiter = RateLimiter(valkey_client, login_lockout_seconds=1)
    identifier = "ip:10.0.0.7:login"

    for _ in range(LOGIN_MAX_FAILURES):
        await limiter.record_login_failure(identifier)
    with pytest.raises(RateLimitError):
        await limiter.check_login_rate(identifier)

    await asyncio.sleep(1.1)  # real TTL expiry on Valkey
    await limiter.check_login_rate(identifier)  # recovered, never permanently locked


async def test_clear_login_failure_resets_counter(valkey_client: Redis) -> None:
    limiter = RateLimiter(valkey_client)
    identifier = "ip:198.51.100.4:login"

    for _ in range(LOGIN_MAX_FAILURES):
        await limiter.record_login_failure(identifier)
    with pytest.raises(RateLimitError):
        await limiter.check_login_rate(identifier)

    await limiter.clear_login_failure(identifier)
    await limiter.check_login_rate(identifier)  # no longer locked


async def test_check_login_with_no_failures_passes(valkey_client: Redis) -> None:
    limiter = RateLimiter(valkey_client)
    await limiter.check_login_rate("ip:203.0.113.9:login")


async def test_resend_verification_cooldown_60s(valkey_client: Redis) -> None:
    limiter = RateLimiter(valkey_client, resend_cooldown_seconds=1)
    account_id = uuid4()

    await limiter.record_resend_verification(account_id)
    with pytest.raises(RateLimitError) as excinfo:
        await limiter.check_resend_verification_quota(account_id)
    assert excinfo.value.error_code == "RATE_LIMITED"

    await asyncio.sleep(1.1)
    await limiter.check_resend_verification_quota(account_id)  # cooldown expired


async def test_resend_verification_max_five_per_24h(valkey_client: Redis) -> None:
    limiter = RateLimiter(valkey_client, resend_cooldown_seconds=0)
    account_id = uuid4()

    for _ in range(5):
        await limiter.record_resend_verification(account_id)
    with pytest.raises(RateLimitError) as excinfo:
        await limiter.check_resend_verification_quota(account_id)
    assert excinfo.value.message  # human-readable limit message


async def test_resend_verification_default_windows(valkey_client: Redis) -> None:
    limiter = RateLimiter(valkey_client)
    account_id = uuid4()

    await limiter.record_resend_verification(account_id)

    cooldown_ttl = await valkey_client.ttl(verify_email_last_sent_key(account_id))
    assert 55 <= cooldown_ttl <= 60  # 60s cooldown
    count_ttl = await valkey_client.ttl(verify_email_count_key(account_id))
    assert 86300 <= count_ttl <= 86400  # 24h window


# ---------------------------------------------------------------------------
# Register rate limiting (Phase 7 review I1 — mandatory mitigation for the
# accepted registration email-existence oracle): dedicated namespace
# ratelimit:register:{identifier}, progressive 5-per-15-min window.
# ---------------------------------------------------------------------------


async def test_register_limit_blocks_after_max_attempts(
    valkey_client: Redis,
) -> None:
    limiter = RateLimiter(valkey_client)
    identifier = "ip:192.168.1.1:register"

    for _ in range(REGISTER_MAX_ATTEMPTS - 1):
        await limiter.record_register_attempt(identifier)
        await limiter.check_register_rate(identifier)  # still allowed below threshold

    await limiter.record_register_attempt(identifier)  # 5th attempt
    with pytest.raises(RateLimitError) as excinfo:
        await limiter.check_register_rate(identifier)
    assert excinfo.value.error_code == "RATE_LIMITED"
    assert excinfo.value.category == "RateLimit"


async def test_register_window_is_15_minutes_by_default(
    valkey_client: Redis,
) -> None:
    limiter = RateLimiter(valkey_client)
    identifier = "ip:10.0.0.9:register"
    for _ in range(REGISTER_MAX_ATTEMPTS):
        await limiter.record_register_attempt(identifier)

    ttl = await valkey_client.ttl(register_rate_key(identifier))
    assert 870 <= ttl <= 900  # 15-minute rolling window


async def test_register_key_namespace_is_separate_from_login(
    valkey_client: Redis,
) -> None:
    """ratelimit:register:{id} must never share state with ratelimit:login:{id}
    (the register limiter counts every valid attempt, the login limiter counts
    failures only — a shared counter would corrupt both)."""
    limiter = RateLimiter(valkey_client)
    identifier = "ip:203.0.113.9:device-1"

    await limiter.record_login_failure(identifier)
    await limiter.record_register_attempt(identifier)
    await limiter.record_register_attempt(identifier)

    await limiter.check_register_rate(identifier)  # login failures do not count
    await limiter.check_login_rate(identifier)  # register attempts do not count


async def test_clear_register_attempts_resets_counter(
    valkey_client: Redis,
) -> None:
    limiter = RateLimiter(valkey_client)
    identifier = "ip:198.51.100.4:register"

    for _ in range(REGISTER_MAX_ATTEMPTS):
        await limiter.record_register_attempt(identifier)
    with pytest.raises(RateLimitError):
        await limiter.check_register_rate(identifier)

    await limiter.clear_register_attempts(identifier)
    await limiter.check_register_rate(identifier)  # no longer throttled
