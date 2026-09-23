"""Plan Task 23: forgot-password / reset-password / reauthenticate routes.

BDD-aligned scenarios (docs/behavior/features/account-auth-session.feature):
- FR-AUTH-024/007: forgot-password returns the IDENTICAL uniform body for
  registered and unregistered emails (no email-existence leak) and is
  rate-limited (429).
- FR-AUTH-025/028: reset with a valid 15-minute secret succeeds once
  (PASSWORD_RESET_TOKEN_INVALID -> 401); replay of a consumed secret -> 401.
- FR-AUTH-026/027: reset revokes ALL old sessions, changes the password hash,
  and does NOT create a session (no Set-Cookie).
- FR-AUTH-034: reauthenticate revalidates the password and establishes a new
  10-minute recent-auth window (INVALID_CREDENTIALS -> 401 on bad password).
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import datetime, timezone

from api.dependencies.auth import get_db_session, get_mailer, get_valkey
from api.main import create_app
from httpx import ASGITransport, AsyncClient
from redis.asyncio import Redis
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

VALID_PASSWORD = "Str0ng#Passw0rd"
NEW_PASSWORD = "N3w-Str0ng#Passw0rd"


class CapturingMailer:
    """Dev test mailer capturing verification + password-reset secrets."""

    def __init__(self) -> None:
        self.sent: list[tuple[str, str, str]] = []  # (kind, email, secret)

    async def send_verification(self, email: str, secret: str) -> None:
        self.sent.append(("verify", email, secret))

    async def send_password_reset(self, email: str, secret: str) -> None:
        self.sent.append(("reset", email, secret))


@asynccontextmanager
async def _client(
    db_session: AsyncSession,
    valkey_client: Redis,
    mailer: CapturingMailer | None = None,
) -> AsyncIterator[AsyncClient]:
    app = create_app(debug=True)
    app.dependency_overrides[get_db_session] = lambda: db_session
    app.dependency_overrides[get_valkey] = lambda: valkey_client
    if mailer is not None:
        app.dependency_overrides[get_mailer] = lambda: mailer
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        yield client


async def _register(client: AsyncClient, email: str) -> int:
    response = await client.post(
        "/v1/auth/register", json={"email": email, "password": VALID_PASSWORD}
    )
    return response.status_code


async def _reset_secret(mailer: CapturingMailer, email: str) -> str:
    for kind, to, secret in mailer.sent:
        if kind == "reset" and to == email:
            return secret
    raise AssertionError(f"no reset mail captured for {email}")


# ---------------------------------------------------------------------------
# POST /v1/auth/forgot-password
# ---------------------------------------------------------------------------


async def test_forgot_password_uniform_for_existing_and_missing(
    db_session: AsyncSession,
    valkey_client: Redis,
) -> None:
    async with _client(db_session, valkey_client) as client:
        await _register(client, "known@example.com")

        known = await client.post(
            "/v1/auth/forgot-password", json={"email": "known@example.com"}
        )
        missing = await client.post(
            "/v1/auth/forgot-password", json={"email": "missing@example.com"}
        )

    assert known.status_code == 200
    assert missing.status_code == 200
    known_body, missing_body = known.json(), missing.json()
    # 防枚举：提示文案与响应结构完全一致；nextAllowedAt 是按请求生成的时间提示，
    # 两次请求间仅有毫秒级差异且与邮箱是否存在无关（同一约定见 resend 路由）。
    assert (
        known_body["messageKey"]
        == missing_body["messageKey"]
        == "FORGOT_PASSWORD_SUCCESS"
    )
    assert known_body.keys() == missing_body.keys()
    known_next = datetime.fromisoformat(known_body["nextAllowedAt"])
    missing_next = datetime.fromisoformat(missing_body["nextAllowedAt"])
    assert known_next > datetime.now(timezone.utc)
    assert abs((known_next - missing_next).total_seconds()) < 5
    assert known_body["nextAllowedAt"]


async def test_forgot_password_repeated_request_429(
    db_session: AsyncSession,
    valkey_client: Redis,
) -> None:
    async with _client(db_session, valkey_client) as client:
        first = await client.post(
            "/v1/auth/forgot-password", json={"email": "repeat@example.com"}
        )
        second = await client.post(
            "/v1/auth/forgot-password", json={"email": "repeat@example.com"}
        )

    assert first.status_code == 200
    assert second.status_code == 429
    assert second.json()["errorCode"] == "RATE_LIMITED"


# ---------------------------------------------------------------------------
# POST /v1/auth/reset-password
# ---------------------------------------------------------------------------


async def test_reset_password_success_revokes_old_sessions_and_changes_hash(
    db_session: AsyncSession,
    valkey_client: Redis,
) -> None:
    mailer = CapturingMailer()
    async with _client(db_session, valkey_client, mailer=mailer) as client:
        await _register(client, "reset@example.com")
        render = await client.post(
            "/v1/auth/forgot-password", json={"email": "reset@example.com"}
        )
        assert render.status_code == 200
        secret = await _reset_secret(mailer, "reset@example.com")

        before = await db_session.execute(
            text(
                "SELECT password_hash FROM auth.password_credentials "
                "WHERE account_id = (SELECT account_id FROM auth.accounts "
                "WHERE normalized_email = 'reset@example.com')"
            )
        )
        old_hash = before.scalar_one()

        response = await client.post(
            "/v1/auth/reset-password",
            json={"token": secret, "newPassword": NEW_PASSWORD},
        )

        after = await db_session.execute(
            text(
                "SELECT password_hash FROM auth.password_credentials "
                "WHERE account_id = (SELECT account_id FROM auth.accounts "
                "WHERE normalized_email = 'reset@example.com')"
            )
        )
        new_hash = after.scalar_one()
        active_sessions = await db_session.scalar(
            text(
                "SELECT count(*) FROM auth.sessions "
                "WHERE account_id = (SELECT account_id FROM auth.accounts "
                "WHERE normalized_email = 'reset@example.com') "
                "AND status = 'Active'"
            )
        )

    assert response.status_code == 200
    body = response.json()
    assert body["messageKey"] == "PASSWORD_RESET_SUCCESS"
    assert body["accountStatus"] == "PendingVerification"
    assert new_hash != old_hash  # FR-AUTH-026.2: old password is dead
    assert int(active_sessions or 0) == 0  # FR-AUTH-026.1: all old sessions revoked

    # No session cookie is created (FR-AUTH-027).
    assert "dom_session" not in {
        line.split("=", 1)[0].strip()
        for line in response.headers.get_list("set-cookie")
    }


async def test_reset_password_old_password_fails_new_password_works(
    db_session: AsyncSession,
    valkey_client: Redis,
) -> None:
    mailer = CapturingMailer()
    async with _client(db_session, valkey_client, mailer=mailer) as client:
        await _register(client, "rotate@example.com")
        await client.post(
            "/v1/auth/forgot-password", json={"email": "rotate@example.com"}
        )
        secret = await _reset_secret(mailer, "rotate@example.com")
        await client.post(
            "/v1/auth/reset-password",
            json={"token": secret, "newPassword": NEW_PASSWORD},
        )

        old_login = await client.post(
            "/v1/auth/login",
            json={"email": "rotate@example.com", "password": VALID_PASSWORD},
        )
        new_login = await client.post(
            "/v1/auth/login",
            json={"email": "rotate@example.com", "password": NEW_PASSWORD},
        )

    assert old_login.status_code == 401  # FR-AUTH-026.2
    assert new_login.status_code == 200  # FR-AUTH-026.3


async def test_reset_password_replay_of_consumed_secret_401(
    db_session: AsyncSession,
    valkey_client: Redis,
) -> None:
    mailer = CapturingMailer()
    async with _client(db_session, valkey_client, mailer=mailer) as client:
        await _register(client, "replay@example.com")
        await client.post(
            "/v1/auth/forgot-password", json={"email": "replay@example.com"}
        )
        secret = await _reset_secret(mailer, "replay@example.com")
        first = await client.post(
            "/v1/auth/reset-password",
            json={"token": secret, "newPassword": NEW_PASSWORD},
        )
        assert first.status_code == 200

        replay = await client.post(
            "/v1/auth/reset-password",
            json={"token": secret, "newPassword": NEW_PASSWORD},
        )

    assert replay.status_code == 401  # FR-AUTH-028: consumed secret rejected
    assert replay.json()["errorCode"] == "PASSWORD_RESET_TOKEN_INVALID"
    assert replay.json()["messageKey"] == "auth.error.passwordResetTokenInvalid"


async def test_reset_password_invalid_secret_401(
    db_session: AsyncSession,
    valkey_client: Redis,
) -> None:
    async with _client(db_session, valkey_client) as client:
        response = await client.post(
            "/v1/auth/reset-password",
            json={"token": "not-a-real-secret", "newPassword": NEW_PASSWORD},
        )

    assert response.status_code == 401
    assert response.json()["errorCode"] == "PASSWORD_RESET_TOKEN_INVALID"


async def test_reset_password_rejects_email_verification_secret(
    db_session: AsyncSession,
    valkey_client: Redis,
) -> None:
    """Minor M-alignment: reset-password must not accept an
    EMAIL_VERIFICATION secret (token_type guard at the route, mirroring
    verify-email). The verification secret stays usable for verify-email —
    the guard rejects without consuming it."""
    mailer = CapturingMailer()
    async with _client(db_session, valkey_client, mailer=mailer) as client:
        await _register(client, "cross-type@example.com")
        assert any(
            kind == "verify" and to == "cross-type@example.com"
            for kind, to, _ in mailer.sent
        ), "registration must have captured a verification secret"
        verify_secret = next(
            secret for kind, to, secret in mailer.sent if kind == "verify"
        )

        misuse = await client.post(
            "/v1/auth/reset-password",
            json={"token": verify_secret, "newPassword": NEW_PASSWORD},
        )
        still_valid = await client.post(
            "/v1/auth/verify-email", json={"token": verify_secret}
        )

    assert misuse.status_code == 401
    assert misuse.json()["errorCode"] == "PASSWORD_RESET_TOKEN_INVALID"
    # Not consumed by the guard: the same secret still verifies the email.
    assert still_valid.status_code == 200
    assert still_valid.json()["messageKey"] == "EMAIL_VERIFIED"


# ---------------------------------------------------------------------------
# POST /v1/auth/reauthenticate
# ---------------------------------------------------------------------------


async def test_reauthenticate_success_establishes_recent_auth_window(
    db_session: AsyncSession,
    valkey_client: Redis,
) -> None:
    async with _client(db_session, valkey_client) as client:
        await _register(client, "reauth@example.com")
        response = await client.post(
            "/v1/auth/reauthenticate", json={"password": VALID_PASSWORD}
        )

    assert response.status_code == 200
    body = response.json()
    assert body["messageKey"] == "REAUTHENTICATED"
    assert body["reauthenticatedAt"]
    assert body["validUntil"]
    assert body["windowSeconds"] == 600  # 10-minute recent-auth window


async def test_reauthenticate_wrong_password_401(
    db_session: AsyncSession,
    valkey_client: Redis,
) -> None:
    async with _client(db_session, valkey_client) as client:
        await _register(client, "reauth-bad@example.com")
        response = await client.post(
            "/v1/auth/reauthenticate", json={"password": "Wrong!Passw0rd"}
        )

    assert response.status_code == 401
    assert response.json()["errorCode"] == "INVALID_CREDENTIALS"


async def test_reauthenticate_without_session_401(
    api_client: AsyncClient,
) -> None:
    response = await api_client.post(
        "/v1/auth/reauthenticate", json={"password": VALID_PASSWORD}
    )
    assert response.status_code == 401
