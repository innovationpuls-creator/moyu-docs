"""Plan Task 22: login / logout / me / session routes.

BDD-aligned scenarios (docs/behavior/features/account-auth-session.feature):
- FR-AUTH-006: valid credentials -> 200 + Active session; PendingVerification
  accounts may log in; Disabled/Deleted accounts are rejected.
- FR-AUTH-007: wrong password vs unknown email -> IDENTICAL 401 Invalid
  Credentials envelope (no email-existence leak).
- FR-AUTH-008: login ALWAYS issues a NEW session id (rotation; never reuses
  the client-provided credential) -> Set-Cookie dom_session != previous value.
- FR-AUTH-035: 5 consecutive failures -> 15-minute temporary lockout (429),
  identical for known and unknown emails.
- FR-AUTH-020: logout only kills the current device session; another device
  stays logged in; logout is idempotent.
- FR-AUTH-009/015/022: /me and /session return account/session facts; a
  replaced session maps to 401 SESSION_REPLACED; expiry to SESSION_EXPIRED.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID

from api.dependencies.auth import get_db_session, get_valkey
from api.main import create_app
from app_core.session.domain.session import (
    Session,
    SessionInvalidationReason,
    SessionStatus,
)
from app_infra.postgres.account_repository import PostgresAccountRepository
from app_infra.valkey.session_cache import ValkeySessionCache
from httpx import ASGITransport, AsyncClient
from redis.asyncio import Redis
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

VALID_PASSWORD = "Str0ng#Passw0rd"


@asynccontextmanager
async def _client(
    db_session: AsyncSession, valkey_client: Redis
) -> AsyncIterator[AsyncClient]:
    app = create_app(debug=True)
    app.dependency_overrides[get_db_session] = lambda: db_session
    app.dependency_overrides[get_valkey] = lambda: valkey_client
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        yield client


def _session_cookie_value(headers: Any) -> str:
    for line in headers.get_list("set-cookie"):
        if line.split("=", 1)[0].strip() == "dom_session":
            return line.split("=", 1)[1].split(";", 1)[0].strip()
    return ""


async def _register(client: AsyncClient, email: str) -> tuple[int, dict[str, Any], str]:
    """Register a fresh account; returns (status, body, session_id)."""
    response = await client.post(
        "/v1/auth/register", json={"email": email, "password": VALID_PASSWORD}
    )
    return (
        response.status_code,
        response.json(),
        _session_cookie_value(response.headers),
    )


async def _login(
    client: AsyncClient, email: str, password: str
) -> tuple[int, dict[str, Any], str]:
    response = await client.post(
        "/v1/auth/login", json={"email": email, "password": password}
    )
    return (
        response.status_code,
        response.json(),
        _session_cookie_value(response.headers),
    )


async def _login_status(client: AsyncClient, email: str, password: str) -> int:
    response = await client.post(
        "/v1/auth/login", json={"email": email, "password": password}
    )
    return response.status_code


# ---------------------------------------------------------------------------
# POST /v1/auth/login
# ---------------------------------------------------------------------------


async def test_login_success_rotates_cookie_and_me_returns_account(
    db_session: AsyncSession,
    valkey_client: Redis,
) -> None:
    async with _client(db_session, valkey_client) as client:
        reg_status, _, reg_session = await _register(client, "alice@example.com")
        assert reg_status == 201
        assert reg_session, "registration must set a session cookie"

        status, body, login_session = await _login(
            client, "alice@example.com", VALID_PASSWORD
        )

        # Rotation (FR-AUTH-008): the login session id must differ from the
        # registration session id — the client-provided credential is never
        # reused, and the cookie jar now points at the NEW session.
        assert status == 200
        assert body["accountStatus"] == "PendingVerification"
        assert body["recoveryModeRequired"] is False
        assert body["session"]["sessionId"] == login_session
        assert body["session"]["currentDevice"] is True
        assert login_session != reg_session
        assert client.cookies.get("dom_session") == login_session

        me = await client.get("/v1/auth/me")
        sess = await client.get("/v1/auth/session")

    assert me.status_code == 200
    me_body = me.json()
    assert me_body["accountId"] == body["accountId"]
    assert me_body["primaryEmail"] == "alice@example.com"
    assert me_body["accountStatus"] == "PendingVerification"
    assert me_body["inAccountRecoveryMode"] is False

    assert sess.status_code == 200
    sess_body = sess.json()
    assert sess_body["sessionId"] == login_session
    assert sess_body["status"] == "Active"
    assert sess_body["currentDevice"] is True
    assert sess_body["lastStrongAuthAt"] is not None


async def test_login_wrong_password_and_unknown_email_identical_401(
    db_session: AsyncSession,
    valkey_client: Redis,
) -> None:
    async with _client(db_session, valkey_client) as client:
        await _register(client, "bob@example.com")

        wrong_pw = await client.post(
            "/v1/auth/login",
            json={"email": "bob@example.com", "password": "Wrong!Passw0rd"},
        )
        unknown = await client.post(
            "/v1/auth/login",
            json={"email": "nobody@example.com", "password": VALID_PASSWORD},
        )

    assert wrong_pw.status_code == 401
    assert unknown.status_code == 401
    wrong, unknown_body = wrong_pw.json(), unknown.json()
    assert wrong["category"] == "Authentication"
    assert wrong["errorCode"] == "INVALID_CREDENTIALS"
    assert wrong["messageKey"] == "auth.error.invalidCredential"
    # 防枚举：两个外部响应完全一致（requestId 属于可变的调用追踪字段，忽略）
    assert wrong["category"] == unknown_body["category"]
    assert wrong["errorCode"] == unknown_body["errorCode"]
    assert wrong["messageKey"] == unknown_body["messageKey"]
    assert wrong["message"] == unknown_body["message"]


async def test_login_after_five_failures_returns_429_lockout(
    db_session: AsyncSession,
    valkey_client: Redis,
) -> None:
    async with _client(db_session, valkey_client) as client:
        await _register(client, "lockout@example.com")
        statuses = [
            await _login_status(client, "lockout@example.com", "Wrong!Passw0rd")
            for _ in range(5)
        ]
        assert statuses == [401, 401, 401, 401, 401]

        locked = await client.post(
            "/v1/auth/login",
            json={"email": "lockout@example.com", "password": VALID_PASSWORD},
        )

    assert locked.status_code == 429
    body = locked.json()
    assert body["category"] == "RateLimit"
    assert body["errorCode"] == "RATE_LIMITED"
    assert body["retryable"] is True


async def test_login_rejected_for_disabled_account(
    db_session: AsyncSession,
    valkey_client: Redis,
) -> None:
    async with _client(db_session, valkey_client) as client:
        await _register(client, "disabled@example.com")
        accounts = PostgresAccountRepository(db_session)
        record = await accounts.find_by_email("disabled@example.com")
        assert record is not None
        record.account.disable()
        await accounts.update(record.account)

        response = await client.post(
            "/v1/auth/login",
            json={"email": "disabled@example.com", "password": VALID_PASSWORD},
        )

    assert response.status_code == 401
    assert response.json()["errorCode"] == "INVALID_CREDENTIALS"


# ---------------------------------------------------------------------------
# POST /v1/auth/logout
# ---------------------------------------------------------------------------


async def test_logout_only_kills_current_device_session(
    db_session: AsyncSession,
    valkey_client: Redis,
) -> None:
    async with _client(db_session, valkey_client) as device_a:
        reg_status, _, _ = await _register(device_a, "multi@example.com")
        assert reg_status == 201

        # Second device logs in — both sessions stay active (2-device quota).
        async with _client(db_session, valkey_client) as device_b:
            login_status, _, _ = await _login(
                device_b, "multi@example.com", VALID_PASSWORD
            )
            assert login_status == 200

            logout = await device_a.post("/v1/auth/logout")

            after_logout = await device_a.get("/v1/auth/me")
            other_device = await device_b.get("/v1/auth/me")

    assert logout.status_code == 200
    assert logout.json()["sessionStatus"] == "LoggedOut"
    assert after_logout.status_code == 401
    assert other_device.status_code == 200


async def test_logout_is_idempotent(
    db_session: AsyncSession,
    valkey_client: Redis,
) -> None:
    async with _client(db_session, valkey_client) as client:
        await _register(client, "idem@example.com")
        first = await client.post("/v1/auth/logout")
        second = await client.post("/v1/auth/logout")

    assert first.status_code == 200
    assert first.json()["sessionStatus"] == "LoggedOut"
    assert second.status_code == 200
    assert second.json()["sessionStatus"] == "AlreadyLoggedOut"


async def test_logout_invalidates_valkey_cache(
    db_session: AsyncSession,
    valkey_client: Redis,
) -> None:
    async with _client(db_session, valkey_client) as client:
        await _register(client, "cache@example.com")
        _, _, session_id = await _login(client, "cache@example.com", VALID_PASSWORD)
        cache = ValkeySessionCache(valkey_client)
        before = await cache.get_session(UUID(session_id))
        assert before is not None  # login caches the new session

        await client.post("/v1/auth/logout")

        after = await cache.get_session(UUID(session_id))

    assert after is None


async def test_me_and_session_unauthenticated_return_401(
    api_client: AsyncClient,
) -> None:
    me = await api_client.get("/v1/auth/me")
    sess = await api_client.get("/v1/auth/session")

    assert me.status_code == 401
    assert sess.status_code == 401
    assert me.json()["category"] == "Authentication"


# ---------------------------------------------------------------------------
# Session lifecycle mapping (FR-AUTH-009/015/021)
# ---------------------------------------------------------------------------


async def test_replaced_session_maps_to_401_session_replaced(
    db_session: AsyncSession,
    valkey_client: Redis,
) -> None:
    """Third-device login replaces the oldest session (createdAt); the replaced
    cookie maps to 401 SESSION_REPLACED (FR-AUTH-015, BDD scenario)."""
    async with _client(db_session, valkey_client) as a:
        await _register(a, "replace@example.com")
        async with _client(db_session, valkey_client) as b:
            await _login(b, "replace@example.com", VALID_PASSWORD)
            async with _client(db_session, valkey_client) as c:
                await _login(c, "replace@example.com", VALID_PASSWORD)

                me = await a.get("/v1/auth/me")

    assert me.status_code == 401
    body = me.json()
    assert body["errorCode"] == "SESSION_REPLACED"
    assert body["messageKey"] == "auth.error.sessionReplaced"
    assert body["category"] == "Authentication"


async def test_cache_flagging_session_replaced_also_maps_to_401(
    db_session: AsyncSession,
    valkey_client: Redis,
) -> None:
    """The Valkey fast path rejects a cached REPLACED snapshot even before the
    authoritative Postgres row is consulted (doc 16 §80/§125-126)."""
    cache = ValkeySessionCache(valkey_client)
    session_id = UUID("00000000-0000-4000-8000-000000000001")
    now = datetime.now(timezone.utc)
    replaced = Session(
        session_id=session_id,
        account_id=UUID("00000000-0000-4000-8000-000000000002"),
        device_id="dev-cache",
        status=SessionStatus.REPLACED,
        created_at=now,
        last_seen_at=now,
        expires_at=now + timedelta(days=90),
        last_strong_auth_at=now,
        invalidation_reason=SessionInvalidationReason.NEW_DEVICE_LOGIN,
        invalidated_at=now,
    )
    await cache.set_session(replaced)

    async with _client(db_session, valkey_client) as client:
        client.cookies.set("dom_session", str(session_id))
        response = await client.get("/v1/auth/me")

    assert response.status_code == 401
    assert response.json()["errorCode"] == "SESSION_REPLACED"


async def test_authoritative_db_expired_session_maps_to_401_session_expired(
    db_session: AsyncSession,
    valkey_client: Redis,
) -> None:
    async with _client(db_session, valkey_client) as client:
        _, _, session_id = await _register(client, "expired@example.com")
        # Force idle expiry: last_seen_at is 31 days in the past (30-day idle).
        await db_session.execute(
            text(
                "UPDATE auth.sessions SET last_seen_at = :at "
                "WHERE session_id = :session_id"
            ),
            {
                "at": datetime.now(timezone.utc) - timedelta(days=31),
                "session_id": session_id,
            },
        )
        # The cache would say ACTIVE; the authoritative Postgres row is expired.
        await db_session.flush()

        response = await client.get("/v1/auth/me")

    assert response.status_code == 401
    assert response.json()["errorCode"] == "SESSION_EXPIRED"


async def test_login_pending_verification_account_succeeds(
    db_session: AsyncSession,
    valkey_client: Redis,
) -> None:
    async with _client(db_session, valkey_client) as client:
        await _register(client, "pending-login@example.com")
        status, body, _ = await _login(
            client, "pending-login@example.com", VALID_PASSWORD
        )

    assert status == 200
    assert body["accountStatus"] == "PendingVerification"
