"""Plan Task 21: registration / verify-email / resend-verification routes.

BDD-aligned scenarios (docs/behavior/features/account-auth-session.feature):

- FR-AUTH-001: new email -> 201, uniform anti-enumeration body, auto session
  cookie; weak/leaked password -> Validation envelope; mail provider failure
  does not block account creation.
- FR-AUTH-005/007: known email -> identical uniform body, NO session cookie,
  no duplicate account row; probed email never leaks existence.
- FR-AUTH-004: resend after >60s cooldown -> 200 with nextAllowedAt; within
  the cooldown (incl. an email sent by registration) -> 429 RATE_LIMITED;
  unknown email gets the SAME uniform payload.
- FR-AUTH-002: valid 24h secret -> account becomes Active, token consumed;
  unknown secret -> 401 EMAIL_VERIFICATION_TOKEN_INVALID; replay -> 401.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from typing import Any

import pytest
from api.dependencies.auth import get_db_session, get_mailer, get_valkey
from api.main import create_app
from app_core.account.application.registration import MailDeliveryError
from app_core.account.domain.account import Account, AccountStatus
from app_core.account.domain.token import OneTimeToken, OneTimeTokenType
from app_infra.postgres.account_repository import PostgresAccountRepository
from app_infra.postgres.token_repository import PostgresTokenRepository
from httpx import ASGITransport, AsyncClient, Headers
from redis.asyncio import Redis
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

VALID_PASSWORD = "Str0ng#Passw0rd"  # 14 chars, BDD FR-AUTH-001


class CapturingMailer:
    """Dev test mailer: records (email, secret) instead of sending."""

    def __init__(self) -> None:
        self.sent: list[tuple[str, str]] = []

    async def send_verification(self, email: str, secret: str) -> None:
        self.sent.append((email, secret))


class FailingMailer:
    """Simulates an external mail provider outage (BDD FR-AUTH-001)."""

    async def send_verification(self, email: str, secret: str) -> None:
        raise MailDeliveryError("provider unreachable")


@asynccontextmanager
async def _client(
    db_session: AsyncSession,
    valkey_client: Redis,
    mailer: Any = None,
    *,
    debug: bool = True,
) -> AsyncIterator[AsyncClient]:
    app = create_app(debug=debug)
    app.dependency_overrides[get_db_session] = lambda: db_session
    app.dependency_overrides[get_valkey] = lambda: valkey_client
    if mailer is not None:
        app.dependency_overrides[get_mailer] = lambda: mailer
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        yield client


async def _register(
    client: AsyncClient, email: str, *, password: str = VALID_PASSWORD
) -> tuple[int, dict[str, Any], Headers]:
    response = await client.post(
        "/v1/auth/register",
        json={"email": email, "password": password},
    )
    return response.status_code, response.json(), response.headers


def _cookie_lines(headers: Headers) -> list[str]:
    return headers.get_list("set-cookie")


def _cookie_names(headers: Headers) -> set[str]:
    names: set[str] = set()
    for line in _cookie_lines(headers):
        name = line.split("=", 1)[0].strip()
        if name:
            names.add(name)
    return names


def _cookie_attribute(headers: Headers, attribute: str) -> bool:
    return any(attribute in line.lower() for line in _cookie_lines(headers))


async def _account_count(db_session: AsyncSession, email: str) -> int:
    count = await db_session.scalar(
        text("SELECT count(*) FROM auth.accounts WHERE normalized_email = :email"),
        {"email": email.casefold()},
    )
    return int(count or 0)


async def _active_session_count(db_session: AsyncSession) -> int:
    count = await db_session.scalar(
        text("SELECT count(*) FROM auth.sessions WHERE status = 'Active'")
    )
    return int(count or 0)


async def _account_status(db_session: AsyncSession, email: str) -> str | None:
    status = await db_session.scalar(
        text("SELECT status FROM auth.accounts WHERE normalized_email = :email"),
        {"email": email.casefold()},
    )
    return status


async def _seed_pending_account(
    db_session: AsyncSession,
    email: str,
    *,
    last_mail_at: datetime,
) -> str:
    """Seed BDD Given state (a PendingVerification account whose last
    verification mail was sent at *last_mail_at*) through the real adapters."""
    account = Account.create_with_email(email, at=last_mail_at)
    await PostgresAccountRepository(db_session).save(account, "hash-placeholder")
    token, secret = OneTimeToken.issue(
        account_id=account.account_id,
        token_type=OneTimeTokenType.EMAIL_VERIFICATION,
        at=last_mail_at,
    )
    await PostgresTokenRepository(db_session).save(token)
    return secret


@pytest.fixture
def recording_mailer() -> CapturingMailer:
    return CapturingMailer()


# ---------------------------------------------------------------------------
# POST /v1/auth/register
# ---------------------------------------------------------------------------


async def test_register_new_email_returns_201_uniform_body_and_session_cookie(
    api_client: AsyncClient,
) -> None:
    status, body, headers = await _register(api_client, "alice@example.com")

    assert status == 201
    assert body == {"messageKey": "REGISTER_SUCCESS", "email": "alice@example.com"}
    assert _cookie_names(headers) == {"dom_device", "dom_session"}
    assert _cookie_attribute(headers, "httponly")
    assert _cookie_attribute(headers, "samesite=lax")


async def test_register_known_email_returns_201_identical_body_without_session_cookie(
    api_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    """USER RULING (2026-09-23): register returns 201 for BOTH new and existing
    emails with an IDENTICAL body; the existing-email response carries NO
    dom_session cookie and creates no new session/account (the cookie absence
    oracle is ACCEPTED, mitigated by register rate limiting + timing shield)."""
    first_status, first_body, first_headers = await _register(
        api_client, "existing@example.com"
    )
    second_status, second_body, second_headers = await _register(
        api_client, "existing@example.com"
    )

    assert first_status == 201
    assert second_status == 201  # identical STATUS for known emails (C1 fix)
    assert first_body == second_body  # 防枚举：两个请求收到完全一致的外部提示
    assert "dom_session" in _cookie_names(first_headers)
    assert "dom_session" not in _cookie_names(second_headers)
    assert await _account_count(db_session, "existing@example.com") == 1
    assert await _active_session_count(db_session) == 1


def _assert_rate_limited_envelope(body: dict[str, Any]) -> None:
    """Canonical 429 RATE_LIMITED envelope shape (error-codes.yaml)."""
    assert body["category"] == "RateLimit"
    assert body["errorCode"] == "RATE_LIMITED"
    assert body["messageKey"] == "auth.error.rateLimited"
    assert body["retryable"] is True


async def test_register_rate_limited_after_five_attempts_known_email(
    db_session: AsyncSession,
    valkey_client: Redis,
) -> None:
    """FR-AUTH-004/035: the register endpoint is throttled per IP+device after
    5 attempts in the 15-minute window — for an email that already exists the
    6th attempt is 429 (attempts 2-5 are the identical existing-email 201s)."""
    async with _client(db_session, valkey_client) as client:
        for _ in range(5):
            status, _, _ = await _register(client, "burst-known@example.com")
            assert status == 201  # 1 new + 4 existing: all identical 201
        sixth_status, sixth_body, _ = await _register(client, "burst-known@example.com")

    assert sixth_status == 429
    _assert_rate_limited_envelope(sixth_body)


async def test_register_rate_limited_after_five_attempts_unknown_email(
    db_session: AsyncSession,
    valkey_client: Redis,
) -> None:
    """Same throttle for emails the service has never seen: because the check
    runs BEFORE the email branch, the 6th attempt is 429 exactly like the
    known-email case (anti-enumeration, FR-AUTH-007)."""
    async with _client(db_session, valkey_client) as client:
        for i in range(5):
            status, _, _ = await _register(client, f"burst-unknown-{i}@example.com")
            assert status == 201
        sixth_status, sixth_body, _ = await _register(
            client, "burst-unknown-5@example.com"
        )

    assert sixth_status == 429
    _assert_rate_limited_envelope(sixth_body)


async def test_register_rate_limit_envelope_identical_for_known_and_unknown(
    db_session: AsyncSession,
    valkey_client: Redis,
) -> None:
    """The 429 payload must be byte-identical for known vs unknown emails so
    throttling itself never leaks email existence."""
    async with _client(db_session, valkey_client) as known_client:
        for _ in range(5):
            await _register(known_client, "env-known@example.com")
        _, known_429, _ = await _register(known_client, "env-known@example.com")
    async with _client(db_session, valkey_client) as unknown_client:
        for i in range(5):
            await _register(unknown_client, f"env-unknown-{i}@example.com")
        _, unknown_429, _ = await _register(unknown_client, "env-unknown-5@example.com")

    assert known_429["category"] == unknown_429["category"] == "RateLimit"
    assert known_429["errorCode"] == unknown_429["errorCode"] == "RATE_LIMITED"
    assert known_429["messageKey"] == unknown_429["messageKey"]
    assert known_429["retryable"] == unknown_429["retryable"] is True


async def test_register_leaked_password_returns_422_password_too_weak_envelope(
    api_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    status, body, _ = await _register(
        api_client, "weak@example.com", password="password1234"
    )

    assert status == 422
    assert body["category"] == "Validation"
    assert body["errorCode"] == "PASSWORD_TOO_WEAK"
    assert body["messageKey"] == "auth.error.passwordTooWeak"
    assert await _account_count(db_session, "weak@example.com") == 0


async def test_register_invalid_email_returns_422_validation_envelope(
    api_client: AsyncClient,
) -> None:
    response = await api_client.post(
        "/v1/auth/register",
        json={"email": "not-an-email", "password": VALID_PASSWORD},
    )

    assert response.status_code == 422
    body = response.json()
    assert body["category"] == "Validation"
    assert body["errorCode"] == "REQUEST_VALIDATION_ERROR"
    assert any(
        field["field"] == "email" and field["code"] == "EMAIL_INVALID"
        for field in (body["fieldErrors"] or [])
    )


async def test_register_mail_provider_failure_still_creates_account_and_session(
    db_session: AsyncSession,
    valkey_client: Redis,
) -> None:
    async with _client(db_session, valkey_client, mailer=FailingMailer()) as client:
        status, body, headers = await _register(client, "outage@example.com")

    assert status == 201
    assert body["messageKey"] == "REGISTER_SUCCESS"
    assert "dom_session" in _cookie_names(headers)
    assert await _account_count(db_session, "outage@example.com") == 1


async def test_register_non_debug_sets_secure_session_cookie(
    db_session: AsyncSession,
    valkey_client: Redis,
) -> None:
    async with _client(db_session, valkey_client, debug=False) as client:
        status, _, headers = await _register(client, "secure@example.com")

    assert status == 201
    assert _cookie_attribute(headers, "secure")
    assert _cookie_attribute(headers, "samesite=lax")


async def test_register_uses_generated_contract_dtos(
    api_client: AsyncClient,
) -> None:
    """Boundary request/response models come from the generated app-contracts
    projection (doc 27 §17 / doc 28 §48), never hand-written duplicates."""
    from app_contracts.commands.auth.register_with_email import (
        RegisterWithEmail,
        RegisterWithEmailResponse,
    )

    assert RegisterWithEmail.model_fields.keys() == {"email", "password"}
    assert RegisterWithEmailResponse.model_fields.keys() == {"messageKey", "email"}
    assert (
        RegisterWithEmail.model_json_schema()["properties"]["email"]["format"]
        == "email"
    )


# ---------------------------------------------------------------------------
# POST /v1/auth/verify-email
# ---------------------------------------------------------------------------


async def test_verify_email_happy_path_activates_account(
    db_session: AsyncSession,
    valkey_client: Redis,
    recording_mailer: CapturingMailer,
) -> None:
    async with _client(db_session, valkey_client, mailer=recording_mailer) as client:
        # 产品已停用注册验证（注册即 Active）；验证端点作为兼容层，用
        # BDD Given 造 Pending 账户来证明它仍可消费验证 token。
        secret = await _seed_pending_account(
            db_session, "eva@example.com", last_mail_at=datetime.now(timezone.utc)
        )
        response = await client.post("/v1/auth/verify-email", json={"token": secret})

    assert response.status_code == 200
    assert response.json() == {
        "messageKey": "EMAIL_VERIFIED",
        "accountStatus": "Active",
    }
    assert await _account_status(db_session, "eva@example.com") == (
        AccountStatus.ACTIVE.value
    )


async def test_verify_email_wrong_token_returns_401_envelope(
    api_client: AsyncClient,
) -> None:
    response = await api_client.post(
        "/v1/auth/verify-email", json={"token": "definitely-not-a-real-secret"}
    )

    assert response.status_code == 401
    body = response.json()
    assert body["category"] == "Authentication"
    assert body["errorCode"] == "EMAIL_VERIFICATION_TOKEN_INVALID"
    assert body["messageKey"] == "auth.error.emailVerificationTokenInvalid"


async def test_verify_email_replay_of_consumed_token_returns_401(
    db_session: AsyncSession,
    valkey_client: Redis,
    recording_mailer: CapturingMailer,
) -> None:
    async with _client(db_session, valkey_client, mailer=recording_mailer) as client:
        secret = await _seed_pending_account(
            db_session, "replay@example.com", last_mail_at=datetime.now(timezone.utc)
        )
        first = await client.post("/v1/auth/verify-email", json={"token": secret})
        assert first.status_code == 200

        replay = await client.post("/v1/auth/verify-email", json={"token": secret})

    assert replay.status_code == 401


# ---------------------------------------------------------------------------
# POST /v1/auth/resend-verification
# ---------------------------------------------------------------------------


async def test_resend_verification_after_cooldown_returns_200(
    db_session: AsyncSession,
    valkey_client: Redis,
) -> None:
    now = datetime.now(timezone.utc)
    await _seed_pending_account(
        db_session, "waited@example.com", last_mail_at=now - timedelta(seconds=120)
    )

    async with _client(db_session, valkey_client) as client:
        response = await client.post(
            "/v1/auth/resend-verification", json={"email": "waited@example.com"}
        )

    assert response.status_code == 200
    body = response.json()
    assert body["messageKey"] == "VERIFICATION_EMAIL_RESENT"
    next_allowed_at = datetime.fromisoformat(body["nextAllowedAt"])
    assert next_allowed_at > now


async def test_resend_verification_within_cooldown_returns_429_rate_limited(
    db_session: AsyncSession,
    valkey_client: Redis,
) -> None:
    now = datetime.now(timezone.utc)
    await _seed_pending_account(
        db_session, "cooldown@example.com", last_mail_at=now - timedelta(seconds=120)
    )

    async with _client(db_session, valkey_client) as client:
        first = await client.post(
            "/v1/auth/resend-verification", json={"email": "cooldown@example.com"}
        )
        second = await client.post(
            "/v1/auth/resend-verification", json={"email": "cooldown@example.com"}
        )

    assert first.status_code == 200
    assert second.status_code == 429
    body = second.json()
    assert body["category"] == "RateLimit"
    assert body["errorCode"] == "RATE_LIMITED"
    assert body["messageKey"] == "auth.error.rateLimited"
    assert body["retryable"] is True


async def test_resend_verification_right_after_registration_mail_is_429(
    db_session: AsyncSession,
    valkey_client: Redis,
) -> None:
    """BDD: '用户刚刚成功触发了一封验证邮件' -> 重发被限流拒绝 (the registration
    mail itself starts the 60s cooldown)."""
    # BDD Given: 账户刚通过注册收到过一封验证邮件（60s 冷却窗口内）。
    await _seed_pending_account(
        db_session, "fresh@example.com", last_mail_at=datetime.now(timezone.utc)
    )
    async with _client(db_session, valkey_client) as client:
        response = await client.post(
            "/v1/auth/resend-verification", json={"email": "fresh@example.com"}
        )

    assert response.status_code == 429
    assert response.json()["errorCode"] == "RATE_LIMITED"


async def test_resend_verification_for_unknown_email_returns_uniform_200(
    api_client: AsyncClient,
) -> None:
    response = await api_client.post(
        "/v1/auth/resend-verification", json={"email": "nobody@example.com"}
    )

    assert response.status_code == 200
    body = response.json()
    # 防枚举：与已注册邮箱返回完全相同的 payload
    assert body["messageKey"] == "VERIFICATION_EMAIL_RESENT"
    assert body["nextAllowedAt"]
