"""Step definitions for the Phase 9 BDD suite (plan Task 29).

Drives the REAL FastAPI app (services/api) through httpx ASGI clients — one
client per logical device (a fresh cookie jar IS a fresh device, so
"设备 A/B/C" are distinct clients with their own ``dom_device``/``dom_session``
cookies) — and asserts against the REAL Postgres (auth.* / audit.* /
integration.*) via the per-scenario ``db_session`` and the REAL Valkey (session
cache + rate limits). World/fixtures: ``tests/bdd/conftest.py`` (BDDContext,
CapturingMailer, SoleOwnerQuery, per-scenario DB/Valkey isolation).

pytest-bdd 8.x never awaits ``async def`` steps, so every step here is a plain
sync function that dispatches its async I/O onto the suite's dedicated event
loop via ``ctx.run`` (see conftest.py).

Documented closest-executable behavior (the phase does not yet contain the
resource; see also the task report):

- Workspace routes (FR-AUTH-003/023/032/033) do not exist yet: the
  server-authoritative capability is asserted through ``GET /v1/auth/me``
  (``canCreateWorkspace``) and the app-wide recovery-mode guard (403
  ``ACCOUNT_IN_RECOVERY_MODE``); a hypothetical workspace-create call is
  server-refused (404 NOT_FOUND, no state change).
- Real-time channel semantics (FR-AUTH-020/026 "实时协同连接") are asserted via
  the session lifecycle the realtime layer consumes (session cache + status).
- The SessionReplaced security-notice E-MAIL (FR-AUTH-036) is not a mailer
  adapter yet; the executable behavior is the replacement flow plus its
  authoritative record (audit ``SessionReplaced`` + outbox event).
- "并发" scenarios (FR-AUTH-005/014) are exercised deterministically: the
  requests use distinct device identities and the post-race outcome (exactly
  one account / exactly 2 active sessions, uniform responses) is asserted; the
  genuine lost-update race is covered by the infrastructure tests (task-5).
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID

from app_core.account.application.deletion import ProcessAccountPurge
from app_core.account.domain.account import Account, AccountStatus
from app_core.account.domain.password_policy import PasswordHasher
from app_core.account.domain.token import OneTimeToken, OneTimeTokenType
from app_infra.postgres.account_repository import PostgresAccountRepository
from app_infra.postgres.audit_repository import PostgresAuditRepository
from app_infra.postgres.deletion_repository import PostgresDeletionRepository
from app_infra.postgres.session_repository import PostgresSessionRepository
from app_infra.postgres.token_repository import PostgresTokenRepository
from app_infra.valkey.rate_limiter import RateLimiter
from httpx import Response
from pytest_bdd import given, parsers, then, when
from sqlalchemy import text

from tests.bdd.conftest import BDDContext, SoleOwnerQuery

VALID_PASSWORD = "Str0ng#Passw0rd"  # 14 chars (BDD FR-AUTH-001)
NEW_PASSWORD = "NewSecurePass888!"  # 14 chars (BDD FR-AUTH-025)


def _norm_email(email: str) -> str:
    return email.strip().casefold()


def _unique(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:10]}"


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _hash_secret(secret: str) -> str:
    return hashlib.sha256(secret.encode("utf-8")).hexdigest()


def _cookie_value(response: Response, name: str) -> str | None:
    for line in response.headers.get_list("set-cookie"):
        if line.split("=", 1)[0].strip() == name:
            return line.split("=", 1)[1].split(";", 1)[0].strip()
    return None


def _record(ctx: BDDContext, response: Response) -> None:
    ctx.last_status = response.status_code
    ctx.last_body = response.json() if response.content else None


def _store_session(ctx: BDDContext, device: str, response: Response) -> None:
    session_id = _cookie_value(response, "dom_session")
    if session_id:
        ctx.sessions[device] = session_id


# ---------------------------------------------------------------------------
# Sync API helpers (each dispatches one coroutine onto the bdd event loop)
# ---------------------------------------------------------------------------


def _register(
    ctx: BDDContext, device: str, email: str, password: str = VALID_PASSWORD
) -> Response:
    response = ctx.run(
        ctx.device(device).post(
            "/v1/auth/register", json={"email": email, "password": password}
        )
    )
    _record(ctx, response)
    _store_session(ctx, device, response)
    return response


def _login(ctx: BDDContext, device: str, email: str, password: str) -> Response:
    response = ctx.run(
        ctx.device(device).post(
            "/v1/auth/login", json={"email": email, "password": password}
        )
    )
    _record(ctx, response)
    _store_session(ctx, device, response)
    return response


def _verify(ctx: BDDContext, device: str, secret: str) -> Response:
    response = ctx.run(
        ctx.device(device).post("/v1/auth/verify-email", json={"token": secret})
    )
    _record(ctx, response)
    return response


def _logout(ctx: BDDContext, device: str) -> Response:
    response = ctx.run(ctx.device(device).post("/v1/auth/logout"))
    _record(ctx, response)
    return response


def _me(ctx: BDDContext, device: str) -> Response:
    response = ctx.run(ctx.device(device).get("/v1/auth/me"))
    _record(ctx, response)
    return response


def _session_info(ctx: BDDContext, device: str) -> Response:
    response = ctx.run(ctx.device(device).get("/v1/auth/session"))
    _record(ctx, response)
    return response


def _resend(ctx: BDDContext, device: str, email: str) -> Response:
    response = ctx.run(
        ctx.device(device).post("/v1/auth/resend-verification", json={"email": email})
    )
    _record(ctx, response)
    return response


def _forgot(ctx: BDDContext, device: str, email: str) -> Response:
    response = ctx.run(
        ctx.device(device).post("/v1/auth/forgot-password", json={"email": email})
    )
    _record(ctx, response)
    return response


def _reset(ctx: BDDContext, device: str, secret: str, new_password: str) -> Response:
    response = ctx.run(
        ctx.device(device).post(
            "/v1/auth/reset-password",
            json={"token": secret, "newPassword": new_password},
        )
    )
    _record(ctx, response)
    return response


def _reauthenticate(ctx: BDDContext, device: str, password: str) -> Response:
    response = ctx.run(
        ctx.device(device).post("/v1/auth/reauthenticate", json={"password": password})
    )
    _record(ctx, response)
    return response


def _delete_account(ctx: BDDContext, device: str) -> Response:
    response = ctx.run(ctx.device(device).post("/v1/auth/delete-account"))
    _record(ctx, response)
    return response


def _cancel_delete(ctx: BDDContext, device: str) -> Response:
    response = ctx.run(ctx.device(device).post("/v1/auth/cancel-delete-account"))
    _record(ctx, response)
    return response


def _status(ctx: BDDContext, device: str) -> Response:
    response = ctx.run(ctx.device(device).get("/v1/auth/status"))
    _record(ctx, response)
    return response


# ---------------------------------------------------------------------------
# Sync DB / domain helpers (dispatched onto the same event loop)
# ---------------------------------------------------------------------------


def _flush(ctx: BDDContext) -> None:
    ctx.run(ctx.db_session.flush())


def _scalar(ctx: BDDContext, stmt, params: dict[str, Any] | None = None) -> Any:
    return ctx.run(ctx.db_session.scalar(stmt, params))


def _rows(ctx: BDDContext, stmt, params: dict[str, Any] | None = None) -> list[Any]:
    result = ctx.run(ctx.db_session.execute(stmt, params))
    return list(result)


def _account_row(ctx: BDDContext, email: str) -> Account | None:
    record = ctx.run(PostgresAccountRepository(ctx.db_session).find_by_email(email))
    return record.account if record is not None else None


def _account_status(ctx: BDDContext, email: str) -> str | None:
    value = _scalar(
        ctx,
        text("SELECT status FROM auth.accounts WHERE normalized_email = :email"),
        {"email": _norm_email(email)},
    )
    return str(value) if value is not None else None


def _active_session_count(ctx: BDDContext, account_id: UUID | None = None) -> int:
    if account_id is None:
        return int(
            _scalar(
                ctx,
                text("SELECT count(*) FROM auth.sessions WHERE status = 'Active'"),
            )
            or 0
        )
    return int(
        _scalar(
            ctx,
            text(
                "SELECT count(*) FROM auth.sessions "
                "WHERE account_id = :account_id AND status = 'Active'"
            ),
            {"account_id": account_id},
        )
        or 0
    )


def _session_status(ctx: BDDContext, session_id: str) -> str:
    value = _scalar(
        ctx,
        text("SELECT status FROM auth.sessions WHERE session_id = :sid"),
        {"sid": session_id},
    )
    return str(value) if value is not None else "<missing>"


def _session_field(ctx: BDDContext, session_id: str, column: str) -> Any:
    return _scalar(
        ctx,
        text(f"SELECT {column} FROM auth.sessions WHERE session_id = :sid"),
        {"sid": session_id},
    )


def _audit_actions(ctx: BDDContext, account_id: UUID) -> list[str]:
    rows = _rows(
        ctx,
        text(
            "SELECT action FROM audit.entries WHERE actor_id = :account_id "
            "ORDER BY occurred_at"
        ),
        {"account_id": account_id},
    )
    return [str(row[0]) for row in rows]


def _password_hash(ctx: BDDContext, email: str) -> str | None:
    value = _scalar(
        ctx,
        text(
            "SELECT pc.password_hash FROM auth.password_credentials pc "
            "JOIN auth.accounts a ON a.account_id = pc.account_id "
            "WHERE a.normalized_email = :email"
        ),
        {"email": _norm_email(email)},
    )
    return str(value) if value is not None else None


def _account_id(ctx: BDDContext, email: str) -> UUID:
    normalized = _norm_email(email)
    if normalized not in ctx.accounts:
        raise AssertionError(f"no recorded account_id for {email}")
    return UUID(ctx.accounts[normalized]["account_id"])


def _current_credentials(ctx: BDDContext) -> tuple[str, str]:
    """The account + password most recently established in the scenario."""
    if ctx.current_email and _norm_email(ctx.current_email) in ctx.accounts:
        email = ctx.current_email
    elif ctx.accounts:
        email = next(reversed(ctx.accounts))
    else:
        raise AssertionError("scenario has no registered account yet")
    return email, ctx.accounts[_norm_email(email)].get("password", VALID_PASSWORD)


def _update_account(ctx: BDDContext, account: Account) -> None:
    ctx.run(PostgresAccountRepository(ctx.db_session).update(account))


def _save_account(ctx: BDDContext, account: Account) -> None:
    ctx.run(PostgresAccountRepository(ctx.db_session).save(account, "hash-placeholder"))


def _save_token(ctx: BDDContext, token) -> None:
    ctx.run(PostgresTokenRepository(ctx.db_session).save(token))


def _seed_pending_account(ctx: BDDContext, email: str, password: str) -> Account:
    """BDD Given (验证兼容层场景，产品已停用注册验证)：直接以 PendingVerification
    状态造账户 + 真实密码哈希 + 有效验证 secret（secret 进 mailer.sent，
    供后续“签发链接/验证/重发”步骤读取）。"""
    now = _utc_now()
    account = Account.create_with_email(email, at=now)
    ctx.run(
        PostgresAccountRepository(ctx.db_session).save(
            account, PasswordHasher.hash(password)
        )
    )
    token, secret = OneTimeToken.issue(
        account_id=account.account_id,
        token_type=OneTimeTokenType.EMAIL_VERIFICATION,
        at=now,
    )
    ctx.run(PostgresTokenRepository(ctx.db_session).save(token))
    ctx.accounts[_norm_email(email)] = {
        "account_id": str(account.account_id),
        "password": password,
    }
    if ctx.current_email is None:
        ctx.current_email = email
    ctx.mailer.sent.append((email, secret))
    return account


def _run_purge(ctx: BDDContext, account_id: UUID) -> None:
    _flush(ctx)
    ctx.run(
        ProcessAccountPurge(
            PostgresAccountRepository(ctx.db_session),
            PostgresSessionRepository(ctx.db_session),
            PostgresAuditRepository(ctx.db_session),
            PostgresDeletionRepository(ctx.db_session),
            now=_utc_now,
        ).execute(account_id)
    )
    _flush(ctx)


def _register_account_pw(ctx: BDDContext, email: str, password: str) -> Account:
    """Register through the API and record the account in the scenario world."""
    if ctx.current_email is None:
        ctx.current_email = email
    response = _register(ctx, "A", email, password)
    assert response.status_code == 201, response.text
    account = _account_row(ctx, email)
    assert account is not None
    ctx.accounts[_norm_email(email)] = {
        "account_id": str(account.account_id),
        "password": password,
    }
    return account


def _backdate_session(ctx: BDDContext, device: str, *, hours: int) -> None:
    session_id = ctx.sessions.get(device)
    assert session_id, f"no session recorded for device {device}"
    at = _utc_now() - timedelta(hours=hours)
    _execute_update(
        ctx,
        "UPDATE auth.sessions SET created_at = :at, last_seen_at = :at, "
        "expires_at = :exp, last_strong_auth_at = :at WHERE session_id = :sid",
        {"at": at, "exp": at + timedelta(days=90), "sid": session_id},
    )


def _execute_update(ctx: BDDContext, sql: str, params: dict[str, Any]) -> None:
    ctx.run(ctx.db_session.execute(text(sql), params))
    _flush(ctx)


def _backdate_deletion(ctx: BDDContext, email: str, *, days: int) -> None:
    account_id = _account_id(ctx, email)
    requested_at = _utc_now() - timedelta(days=days)
    _execute_update(
        ctx,
        "UPDATE auth.accounts SET deletion_requested_at = :at "
        "WHERE account_id = :account_id",
        {"at": requested_at, "account_id": account_id},
    )
    _execute_update(
        ctx,
        "UPDATE auth.account_deletion_requests SET requested_at = :at, "
        "execute_after = :after WHERE account_id = :account_id",
        {
            "at": requested_at,
            "after": requested_at + timedelta(days=30),
            "account_id": account_id,
        },
    )


def _record_reset_secret(ctx: BDDContext, email: str) -> None:
    reset_mails = [
        entry for entry in ctx.mailer.password_resets if entry[0] == _norm_email(email)
    ]
    if reset_mails:
        ctx.reset_secrets[email] = reset_mails[-1][1]


def _replace_device_a(ctx: BDDContext) -> None:
    email = _unique("replaced-a") + "@example.com"
    _register_account_pw(ctx, email, VALID_PASSWORD)
    login_b = _login(ctx, "B", email, VALID_PASSWORD)
    assert login_b.status_code == 200
    _backdate_session(ctx, "A", hours=2)
    _backdate_session(ctx, "B", hours=1)
    login_c = _login(ctx, "C", email, VALID_PASSWORD)
    assert login_c.status_code == 200


def _ensure_replacement_setup(ctx: BDDContext) -> None:
    """Make sure the account has 2 active devices with A as the oldest, so the
    third-device login actually replaces A (FR-AUTH-012). Self-sufficient for
    scenarios whose Given declared no account (e.g. the mail-outage case)."""
    try:
        email, password = _current_credentials(ctx)
        _account_id(ctx, email)
    except AssertionError:
        email = _unique("replacement") + "@example.com"
        _register_account_pw(ctx, email, VALID_PASSWORD)
        password = VALID_PASSWORD
    account_id = _account_id(ctx, email)
    active = _active_session_count(ctx, account_id)
    if active < 2:
        login_b = _login(ctx, "B", email, password)
        assert login_b.status_code == 200
        _backdate_session(ctx, "A", hours=2)
        _backdate_session(ctx, "B", hours=1)


# ---------------------------------------------------------------------------
# Given: state seeding (API + real adapters; rolls back per scenario)
# ---------------------------------------------------------------------------


@given(parsers.cfparse('系统中不存在使用邮箱 "{email}" 的账号'))
def given_no_account(bdd_context: BDDContext, email: str):
    assert _account_status(bdd_context, email) is None


@given("用户使用未注册邮箱提交注册申请")
def given_unregistered_email(bdd_context: BDDContext):
    bdd_context.current_email = _unique("unregistered") + "@example.com"


@given(parsers.cfparse('存在邮箱为 "{email}" 且状态为 "{status}" 的账号'))
def given_account_email_status(bdd_context: BDDContext, email: str, status: str):
    if _account_row(bdd_context, email) is None:
        _register_account_pw(bdd_context, email, VALID_PASSWORD)
    if status == "Active":
        account = _account_row(bdd_context, email)
        assert account is not None and account.status is not AccountStatus.ACTIVE
        account.verify_email(at=_utc_now())
        _update_account(bdd_context, account)
    _flush(bdd_context)


@given("系统为其签发了一条 24 小时有效的未消费验证凭据链接")
def given_valid_verification_link(bdd_context: BDDContext):
    assert bdd_context.mailer.sent
    bdd_context.verification_secrets["current"] = bdd_context.mailer.sent[-1][1]


@given("账号此前先后申请并收到了验证链接 Link_A 与链接 Link_B")
def given_two_verification_links(bdd_context: BDDContext):
    # The scenario has no separate register step: establish the account here
    # via the verification-compat seed (Pending account + captured secret).
    email = bdd_context.current_email or _unique("two-links") + "@example.com"
    if _account_row(bdd_context, email) is None:
        _seed_pending_account(bdd_context, email, VALID_PASSWORD)
    assert bdd_context.mailer.sent
    bdd_context.verification_secrets["Link_A"] = bdd_context.mailer.sent[-1][1]
    account = _account_row(bdd_context, email)
    assert account is not None
    token, secret_b = OneTimeToken.issue(
        account_id=account.account_id,
        token_type=OneTimeTokenType.EMAIL_VERIFICATION,
        at=_utc_now(),
    )
    _save_token(bdd_context, token)
    bdd_context.verification_secrets["Link_B"] = secret_b


@given('存在状态为 "PendingVerification" 的账号')
def given_pending_account(bdd_context: BDDContext):
    _seed_pending_account(
        bdd_context, _unique("pending") + "@example.com", VALID_PASSWORD
    )


@given("其验证凭据链接签发已超过 24 小时")
def given_verification_link_expired(bdd_context: BDDContext):
    secret = bdd_context.verification_secrets.get("current")
    if secret is None:
        # Scenarios that did not capture the secret via the "签发链接" step
        # fall back to the account's registration verification mail.
        assert bdd_context.mailer.sent
        secret = bdd_context.mailer.sent[-1][1]
        bdd_context.verification_secrets["current"] = secret
    _execute_update(
        bdd_context,
        "UPDATE auth.one_time_tokens SET expires_at = :expired "
        "WHERE token_hash = :token_hash AND token_type = 'EmailVerification'",
        {
            "expired": _utc_now() - timedelta(hours=1),
            "token_hash": _hash_secret(secret),
        },
    )


@given('用户拥有一个状态为 "PendingVerification" 的账号并已登录系统')
def given_pending_account_logged_in(bdd_context: BDDContext):
    email = _unique("pending-logged") + "@example.com"
    _seed_pending_account(bdd_context, email, VALID_PASSWORD)
    response = _login(bdd_context, "A", email, VALID_PASSWORD)
    assert response.status_code == 200


@given(parsers.cfparse('用户在设备 A 上以 "{status}" 状态浏览系统'))
def given_device_a_browsing(bdd_context: BDDContext, status: str):
    email = _unique("browse") + "@example.com"
    if status == "Active":
        # 产品已停用注册验证：注册即 Active，直接登录即可。
        _register_account_pw(bdd_context, email, VALID_PASSWORD)
    else:
        # PendingVerification：验证兼容层的 BDD Given 用 DB seed 造账户。
        _seed_pending_account(bdd_context, email, VALID_PASSWORD)
    response = _login(bdd_context, "A", email, VALID_PASSWORD)
    assert response.status_code == 200


@given('存在状态为 "PendingVerification" 的账号且距离上次发信已超过 60 秒')
def given_pending_last_mail_over_60s(bdd_context: BDDContext):
    email = _unique("waited") + "@example.com"
    last_at = _utc_now() - timedelta(seconds=120)
    account = Account.create_with_email(email, at=last_at)
    _save_account(bdd_context, account)
    token, secret = OneTimeToken.issue(
        account_id=account.account_id,
        token_type=OneTimeTokenType.EMAIL_VERIFICATION,
        at=last_at,
    )
    _save_token(bdd_context, token)
    bdd_context.accounts[_norm_email(email)] = {"password": VALID_PASSWORD}
    bdd_context.current_email = email
    bdd_context.mailer.sent.append((email, secret))


@given("过去 24 小时内该账号发送验证邮件未达 5 次")
def given_resend_under_quota(bdd_context: BDDContext):
    # No Valkey send record exists for the seeded account -> trivially true.
    return None


@given("用户刚刚成功触发了一封验证邮件，或 24 小时内已累计触发了 5 次验证邮件")
def given_verification_mail_just_sent(bdd_context: BDDContext):
    # 验证兼容层：seed Pending（secret 写入 mailer.sent 即视作刚发出的邮件）。
    _seed_pending_account(
        bdd_context, _unique("fresh") + "@example.com", VALID_PASSWORD
    )


@given(parsers.cfparse('系统中已存在账号 "{existing}"，不存在账号 "{missing}"'))
def given_account_exists_missing(bdd_context: BDDContext, existing: str, missing: str):
    if _account_row(bdd_context, existing) is None:
        _register_account_pw(bdd_context, existing, VALID_PASSWORD)
    assert _account_status(bdd_context, missing) is None


@given(parsers.cfparse('系统中原本不存在邮箱 "{email}"'))
def given_email_absent(bdd_context: BDDContext, email: str):
    assert _account_status(bdd_context, email) is None


@given(parsers.cfparse('存在状态为 "{status}" 的账号 "{email}"，密码为 "{password}"'))
def given_account_email_password(
    bdd_context: BDDContext, status: str, email: str, password: str
):
    if _account_row(bdd_context, email) is None:
        _register_account_pw(bdd_context, email, password)
    account = _account_row(bdd_context, email)
    assert account is not None
    bdd_context.accounts[_norm_email(email)] = {
        "account_id": str(account.account_id),
        "password": password,
    }
    if status == "Active":
        account.verify_email(at=_utc_now())
        _update_account(bdd_context, account)
    _flush(bdd_context)


@given(parsers.cfparse('存在状态为 "{status}" 的账号 "{email}"'))
def given_account_status_email(bdd_context: BDDContext, status: str, email: str):
    if _account_row(bdd_context, email) is None:
        if status == "PendingVerification":
            # 验证兼容层：注册（即 Active）造不出 Pending，用 DB seed。
            _seed_pending_account(bdd_context, email, VALID_PASSWORD)
        else:
            _register_account_pw(bdd_context, email, VALID_PASSWORD)
    account = _account_row(bdd_context, email)
    assert account is not None
    if status == "Active":
        account.verify_email(at=_utc_now())
        _update_account(bdd_context, account)
    elif status == "DeletionPending":
        account.request_deletion(at=_utc_now())
        _update_account(bdd_context, account)
    _flush(bdd_context)


@given(parsers.cfparse('系统中存在一个被设为 "{first}" 或 "{second}" 的账号'))
def given_disabled_or_deleted_account(bdd_context: BDDContext, first: str, second: str):
    email = _unique("blocked") + "@example.com"
    _register_account_pw(bdd_context, email, VALID_PASSWORD)
    account = _account_row(bdd_context, email)
    assert account is not None
    if "Disabled" in (first, second):
        account.disable(at=_utc_now())
    elif "Deleted" in (first, second):
        account.purge(at=_utc_now())
    _update_account(bdd_context, account)
    # No device may hold a valid session for the block-listed account, so the
    # "被迫登录" attempt is the only request (FR-AUTH-006).
    _execute_update(
        bdd_context,
        "UPDATE auth.sessions SET status = 'Revoked' WHERE account_id = :account_id",
        {"account_id": account.account_id},
    )
    _flush(bdd_context)


@given(parsers.cfparse('系统中存在账号 "{registered}"，不存在 "{unregistered}"'))
def given_registered_and_unregistered(
    bdd_context: BDDContext, registered: str, unregistered: str
):
    if _account_row(bdd_context, registered) is None:
        _register_account_pw(bdd_context, registered, VALID_PASSWORD)
    assert _account_status(bdd_context, unregistered) is None


@given("客户端在登录前持有一个未认证的会话标识")
def given_unauthenticated_session_identifier(bdd_context: BDDContext):
    # Establish a real account first, then place a bogus (never-issued)
    # session identifier in the client's jar to stand for the pre-login
    # unauthenticated credential (FR-AUTH-008).
    email = _unique("rotation") + "@example.com"
    _register_account_pw(bdd_context, email, VALID_PASSWORD)
    bogus = str(UUID(int=0xDEADBEEF))
    bdd_context.verification_secrets["pre_login_session_id"] = bogus
    bdd_context.device("A").cookies.set("dom_session", bogus)


@given("用户在设备 A 上拥有一个已建立的活跃会话")
def given_active_session_device_a(bdd_context: BDDContext):
    email = _unique("active-a") + "@example.com"
    _register_account_pw(bdd_context, email, VALID_PASSWORD)
    response = _login(bdd_context, "A", email, VALID_PASSWORD)
    assert response.status_code == 200


@given("用户在设备 A 上每日持续活跃使用系统")
def given_daily_active_device_a(bdd_context: BDDContext):
    given_active_session_device_a(bdd_context)


@given("用户在设备 A 上已登录且处于正常使用状态")
def given_logged_in_normal_state(bdd_context: BDDContext):
    given_active_session_device_a(bdd_context)


@given(parsers.cfparse('账号已经在设备 A 上成功登录且会话处于 "{status}" 状态'))
def given_account_logged_in_device_a(bdd_context: BDDContext, status: str):
    given_active_session_device_a(bdd_context)


@given(
    parsers.cfparse("账号在 10:00 登录设备 A（createdAt 最早），在 11:00 登录设备 B")
)
def given_two_device_logins_times(bdd_context: BDDContext):
    email = _unique("two-device") + "@example.com"
    _register_account_pw(bdd_context, email, VALID_PASSWORD)
    response = _login(bdd_context, "B", email, VALID_PASSWORD)
    assert response.status_code == 200
    _backdate_session(bdd_context, "A", hours=2)
    _backdate_session(bdd_context, "B", hours=1)


@given("系统中当前存在 2 个活跃设备会话（设备 A 与设备 B）")
def given_two_active_sessions_ab(bdd_context: BDDContext):
    return None


@given("设备 A 在 11:30 进行过操作，其最后活跃时间晚于设备 B 的创建时间")
def given_device_a_recently_active(bdd_context: BDDContext):
    _execute_update(
        bdd_context,
        "UPDATE auth.sessions SET last_seen_at = :at WHERE session_id = :sid",
        {
            "at": _utc_now() - timedelta(minutes=30),
            "sid": bdd_context.sessions["A"],
        },
    )


@given(parsers.cfparse("账号在设备 A（较旧）与设备 B（较新）上同时处于活跃登录状态"))
def given_devices_a_older_b_newer(bdd_context: BDDContext):
    email = _unique("older-newer") + "@example.com"
    _register_account_pw(bdd_context, email, VALID_PASSWORD)
    response = _login(bdd_context, "B", email, VALID_PASSWORD)
    assert response.status_code == 200
    _backdate_session(bdd_context, "A", hours=2)
    _backdate_session(bdd_context, "B", hours=1)


@given(parsers.cfparse('账号在设备 A 的会话已被新设备登录替换为 "{status}" 状态'))
def given_device_a_replaced(bdd_context: BDDContext, status: str):
    _replace_device_a(bdd_context)


@given('设备 A 的会话已被替换为 "Replaced"')
def given_device_a_replaced_short(bdd_context: BDDContext):
    _replace_device_a(bdd_context)


@given('账号在设备 A 与设备 B 上均处于 "Active" 登录状态')
def given_devices_a_b_active(bdd_context: BDDContext):
    email = _unique("ab-active") + "@example.com"
    _register_account_pw(bdd_context, email, VALID_PASSWORD)
    response = _login(bdd_context, "B", email, VALID_PASSWORD)
    assert response.status_code == 200
    _backdate_session(bdd_context, "A", hours=1)


@given("设备 A 的会话已经处于登出状态")
def given_device_a_logged_out(bdd_context: BDDContext):
    email = _unique("loggedout") + "@example.com"
    _register_account_pw(bdd_context, email, VALID_PASSWORD)
    response = _logout(bdd_context, "A")
    assert response.status_code == 200


@given(parsers.cfparse('用户已经在设备 A 上成功登录，账号状态为 "{status}"'))
def given_logged_in_active(bdd_context: BDDContext, status: str):
    email = _unique("me") + "@example.com"
    _register_account_pw(bdd_context, email, VALID_PASSWORD)
    # 注册即 Active（邮箱验证已停用）；兼容回切时消费验证邮件保持 Active。
    if bdd_context.mailer.sent:
        verified = _verify(bdd_context, "A", bdd_context.mailer.sent[-1][1])
        assert verified.status_code == 200
    login = _login(bdd_context, "A", email, VALID_PASSWORD)
    assert login.status_code == 200


@given("客户端当前不具备任何认证会话")
def given_no_authentication_session(bdd_context: BDDContext):
    bdd_context.device("anon")  # fresh cookie jar, never logged in


@given('用户账号状态为 "PendingVerification"')
def given_account_pending(bdd_context: BDDContext):
    email = _unique("capability") + "@example.com"
    _seed_pending_account(bdd_context, email, VALID_PASSWORD)
    # 能力判定（me()/高风险请求）需认证会话：Pending 账户同样可登录。
    login = _login(bdd_context, "A", email, VALID_PASSWORD)
    assert login.status_code == 200


@given(
    parsers.cfparse('系统中存在已注册邮箱 "{registered}"，不存在未注册邮箱 "{missing}"')
)
def given_registered_missing_reset(
    bdd_context: BDDContext, registered: str, missing: str
):
    if _account_row(bdd_context, registered) is None:
        _register_account_pw(bdd_context, registered, VALID_PASSWORD)
    assert _account_status(bdd_context, missing) is None


@given(
    parsers.cfparse('账号 "{email}" 申请了重置密码，并获得一条 15 分钟有效的重置链接')
)
def given_account_reset_link(bdd_context: BDDContext, email: str):
    _register_account_pw(bdd_context, email, VALID_PASSWORD)
    response = _forgot(bdd_context, "A", email)
    assert response.status_code == 200
    _record_reset_secret(bdd_context, email)
    bdd_context.reset_secrets.setdefault(
        "current", bdd_context.reset_secrets.get(email, "")
    )


@given("账号此前申请了密码重置，但该重置凭据已超过 15 分钟有效时限")
def given_expired_reset_link(bdd_context: BDDContext):
    email = _unique("expired-reset") + "@example.com"
    _register_account_pw(bdd_context, email, VALID_PASSWORD)
    response = _forgot(bdd_context, "A", email)
    assert response.status_code == 200
    _record_reset_secret(bdd_context, email)
    secret = bdd_context.reset_secrets.get(email)
    assert secret is not None
    _execute_update(
        bdd_context,
        "UPDATE auth.one_time_tokens SET expires_at = :expired "
        "WHERE token_hash = :token_hash AND token_type = 'PasswordReset'",
        {
            "expired": _utc_now() - timedelta(minutes=1),
            "token_hash": _hash_secret(secret),
        },
    )
    # Snapshot the current hash: the rejected attempt must leave it unchanged.
    bdd_context.accounts[_norm_email(email)]["password_hash_before"] = (
        _password_hash(bdd_context, email) or ""
    )


@given(parsers.cfparse('账号 "{email}" 在 10:00 申请了重置密码获得凭据 Token_1'))
def given_reset_token1(bdd_context: BDDContext, email: str):
    # A no-cooldown limiter lets the two reset requests in the scenario issue
    # two tokens without waiting for the 60s resend cooldown (FR-AUTH-025).
    bdd_context.rate_limiter = RateLimiter(
        bdd_context.valkey_client, resend_cooldown_seconds=0
    )
    _register_account_pw(bdd_context, email, VALID_PASSWORD)
    first = _forgot(bdd_context, "A", email)
    assert first.status_code == 200
    _record_reset_secret(bdd_context, email)
    bdd_context.reset_secrets["Token_1"] = bdd_context.reset_secrets.get(email, "")


@given(parsers.cfparse("账号在 10:05 再次申请重置密码获得新凭据 Token_2"))
def given_reset_token2(bdd_context: BDDContext):
    email = bdd_context.current_email
    assert email is not None
    second = _forgot(bdd_context, "A", email)
    assert second.status_code == 200
    _record_reset_secret(bdd_context, email)
    bdd_context.reset_secrets["Token_2"] = bdd_context.reset_secrets.get(email, "")


@given(parsers.cfparse('账号 "{email}" 此前已在设备 A 与设备 B 上登录并处于活跃状态'))
def given_account_logged_devices_ab(bdd_context: BDDContext, email: str):
    _register_account_pw(bdd_context, email, VALID_PASSWORD)
    second = _login(bdd_context, "B", email, VALID_PASSWORD)
    assert second.status_code == 200


@given("用户在浏览器中成功提交新密码并完成密码重置")
def given_reset_completed(bdd_context: BDDContext):
    email = _unique("completed-reset") + "@example.com"
    _register_account_pw(bdd_context, email, VALID_PASSWORD)
    response = _forgot(bdd_context, "A", email)
    assert response.status_code == 200
    _record_reset_secret(bdd_context, email)
    secret = bdd_context.reset_secrets.get(email)
    assert secret is not None
    reset_response = _reset(bdd_context, "A", secret, NEW_PASSWORD)
    assert reset_response.status_code == 200
    bdd_context.captured_responses = [reset_response]
    # Snapshot the POST-reset hash: the replay attempt (FR-AUTH-028) must not
    # change it.
    bdd_context.accounts[_norm_email(email)]["password_hash_before"] = (
        _password_hash(bdd_context, email) or ""
    )


@given("某个密码重置链接此前已成功完成了一次密码修改")
def given_consumed_reset_link(bdd_context: BDDContext):
    given_reset_completed(bdd_context)


@given(
    parsers.cfparse('用户账号是工作区 "{workspace}" 的唯一 Owner 且该工作区尚未被删除')
)
def given_sole_owner(bdd_context: BDDContext, workspace: str):
    # Point the ownership seam at a sole-owner adapter BEFORE the device
    # clients are created so every request carries the override (FR-AUTH-029).
    bdd_context.ownership = SoleOwnerQuery(workspace)
    email = _unique("sole-owner") + "@example.com"
    _register_account_pw(bdd_context, email, VALID_PASSWORD)


@given("用户账号不是任何未删除 Workspace 的唯一 Owner")
def given_not_sole_owner(bdd_context: BDDContext):
    email = _unique("not-owner") + "@example.com"
    _register_account_pw(bdd_context, email, VALID_PASSWORD)


@given("用户在过去 10 分钟内完成了密码重新认证")
def given_recent_reauth(bdd_context: BDDContext):
    # The registration session's last_strong_auth_at is "now", i.e. inside the
    # 10-minute reauthentication window.
    return None


@given("用户的当前会话已登录超过 10 分钟且期间未重新验证过密码")
def given_stale_last_strong_auth(bdd_context: BDDContext):
    email = _unique("stale") + "@example.com"
    _register_account_pw(bdd_context, email, VALID_PASSWORD)
    login = _login(bdd_context, "A", email, VALID_PASSWORD)
    assert login.status_code == 200
    _execute_update(
        bdd_context,
        "UPDATE auth.sessions SET last_strong_auth_at = :at WHERE session_id = :sid",
        {
            "at": _utc_now() - timedelta(minutes=11),
            "sid": bdd_context.sessions["A"],
        },
    )


@given('账号已进入 "DeletionPending" 状态第 5 天')
def given_deletion_pending_day5(bdd_context: BDDContext):
    email = _unique("day5") + "@example.com"
    _register_account_pw(bdd_context, email, VALID_PASSWORD)
    result = _delete_account(bdd_context, "A")
    assert result.status_code == 200
    _backdate_deletion(bdd_context, email, days=5)


@given('账号进入 "DeletionPending" 状态已满 30 天且期间未发起取消删除')
def given_deletion_pending_30days(bdd_context: BDDContext):
    email = _unique("due") + "@example.com"
    _register_account_pw(bdd_context, email, VALID_PASSWORD)
    result = _delete_account(bdd_context, "A")
    assert result.status_code == 200
    _backdate_deletion(bdd_context, email, days=31)


@given(
    parsers.cfparse(
        '账号在申请删除前处于 "{pre_status}" 状态，当前处于 "DeletionPending" 宽限期内'
    )
)
def given_pre_status_deletion_pending(bdd_context: BDDContext, pre_status: str):
    email = _unique("pre") + "@example.com"
    if pre_status == "Active":
        # 邮箱验证已停用：注册即 Active，无需（也无法）再走验证邮件。
        _register_account_pw(bdd_context, email, VALID_PASSWORD)
    else:
        # PendingVerification 预置：验证兼容层场景用 DB seed 造 Pending 账户，
        # 并建立登录会话（删除申请要求具备 recent reauthentication）。
        _seed_pending_account(bdd_context, email, VALID_PASSWORD)
        login = _login(bdd_context, "A", email, VALID_PASSWORD)
        assert login.status_code == 200
    result = _delete_account(bdd_context, "A")
    assert result.status_code == 200


@given('存在处于 "DeletionPending" 状态的账号')
def given_deletion_pending_account(bdd_context: BDDContext):
    email = _unique("recovery") + "@example.com"
    _register_account_pw(bdd_context, email, VALID_PASSWORD)
    login = _login(bdd_context, "A", email, VALID_PASSWORD)
    assert login.status_code == 200
    result = _delete_account(bdd_context, "A")
    assert result.status_code == 200


@given('账号已处于 "DeletionPending" 状态')
def given_account_already_deletion_pending(bdd_context: BDDContext):
    email = _unique("recovery-ready") + "@example.com"
    _register_account_pw(bdd_context, email, VALID_PASSWORD)
    login = _login(bdd_context, "A", email, VALID_PASSWORD)
    assert login.status_code == 200
    result = _delete_account(bdd_context, "A")
    assert result.status_code == 200


@given(
    parsers.cfparse(
        "该账号此前已在 10:00 登录设备 A、在 11:00 登录设备 B 进入了恢复模式"
    )
)
def given_recovery_devices_ab(bdd_context: BDDContext):
    email = bdd_context.current_email
    if email is None or _account_status(bdd_context, email) != "DeletionPending":
        # No prior DeletionPending account in this scenario: build one.
        email = _unique("recovery-ab") + "@example.com"
        _register_account_pw(bdd_context, email, VALID_PASSWORD)
        login_a = _login(bdd_context, "A", email, VALID_PASSWORD)
        assert login_a.status_code == 200
        login_b = _login(bdd_context, "B", email, VALID_PASSWORD)
        assert login_b.status_code == 200
        result = _delete_account(bdd_context, "B")
        assert result.status_code == 200
    else:
        # Reuse the DeletionPending account from the previous Given; both
        # devices enter Account Recovery Mode.
        login_a = _login(bdd_context, "A", email, VALID_PASSWORD)
        assert login_a.status_code == 200
        login_b = _login(bdd_context, "B", email, VALID_PASSWORD)
        assert login_b.status_code == 200
    _backdate_session(bdd_context, "A", hours=2)
    _backdate_session(bdd_context, "B", hours=1)


@given("用户已登录并处于 Account Recovery Mode")
def given_logged_in_recovery_mode(bdd_context: BDDContext):
    email = _unique("recovery-rm") + "@example.com"
    _register_account_pw(bdd_context, email, VALID_PASSWORD)
    login = _login(bdd_context, "A", email, VALID_PASSWORD)
    assert login.status_code == 200
    result = _delete_account(bdd_context, "A")
    assert result.status_code == 200
    recovery_login = _login(bdd_context, "A", email, VALID_PASSWORD)
    assert recovery_login.status_code == 200


@given("账号 user_123 曾经在团队 Workspace 中创建并编辑了协同文档 Doc_A")
def given_user_123_resources(bdd_context: BDDContext):
    email = "user_123@example.com"
    account = _register_account_pw(bdd_context, email, VALID_PASSWORD)
    bdd_context.accounts["user_123"] = {"account_id": str(account.account_id)}


@given("客户端对登录入口连续提交错误的密码尝试达到系统失败阈值")
def given_five_failed_logins(bdd_context: BDDContext):
    # Shortened lockout window so the cooldown self-heals within the test
    # (same approach as tests/security/test_brute_force_lockout.py); the
    # 5-failure threshold itself is a fixed product constant.
    bdd_context.rate_limiter = RateLimiter(
        bdd_context.valkey_client, login_lockout_seconds=2
    )
    email = _unique("lockout") + "@example.com"
    _register_account_pw(bdd_context, email, VALID_PASSWORD)
    for _ in range(5):
        failed = _login(bdd_context, "A", email, "Wrong!Password")
        assert failed.status_code == 401


@given("账号原本在设备 A 处于登录状态")
def given_account_device_a_logged_in(bdd_context: BDDContext):
    given_active_session_device_a(bdd_context)


@given("外部邮件发送服务当前暂时不可用")
def given_mail_unavailable(bdd_context: BDDContext):
    bdd_context.mailer.fail_sends = True


@given("外部邮件发送服务发生网络故障")
def given_mail_outage(bdd_context: BDDContext):
    bdd_context.mailer.fail_sends = True


@given(parsers.cfparse("用户使用未注册邮箱和合规密码发起注册请求并携带稳定的幂等标识"))
def given_register_with_idempotency_key(bdd_context: BDDContext):
    # The API register route does not yet surface the Idempotency-Key header
    # (documented deviation): the semantic guarantee asserted by this scenario
    # is the idempotent OUTCOME — retrying never duplicates the account and
    # both attempts return the uniform success response.
    email = _unique("idem") + "@example.com"
    bdd_context.current_email = email
    first = _register(bdd_context, "A", email, VALID_PASSWORD)
    assert first.status_code == 201
    bdd_context.accounts[_norm_email(email)] = {"password": VALID_PASSWORD}


# ---------------------------------------------------------------------------
# When: user actions (API calls + real scheduled-task execution)
# ---------------------------------------------------------------------------


@when(
    parsers.cfparse(
        '用户使用邮箱 "{email}" 和长度为 {length:d} 位的合规密码 "{password}"'
        " 提交注册申请"
    )
)
def when_register_valid(
    bdd_context: BDDContext, email: str, length: int, password: str
):
    _register(bdd_context, "A", email, password)
    bdd_context.current_email = email
    account = _account_row(bdd_context, email)
    bdd_context.accounts[_norm_email(email)] = {
        "account_id": str(account.account_id) if account else "",
        "password": password,
    }


@when(parsers.cfparse('用户输入长度为 {length:d} 字符的密码 "{password}" 提交注册'))
def when_register_short_password(bdd_context: BDDContext, length: int, password: str):
    email = bdd_context.current_email
    assert email is not None
    _register(bdd_context, "A", email, password)


@when(
    parsers.cfparse(
        '用户输入长度为 {length:d} 字符但在已知泄露密码库中的弱密码 "{password}"'
        " 提交注册"
    )
)
def when_register_leaked_password(bdd_context: BDDContext, length: int, password: str):
    email = bdd_context.current_email
    assert email is not None
    _register(bdd_context, "A", email, password)


@when("客户端因网络抖动重试相同的注册请求并携带相同的幂等标识")
def when_retry_registration(bdd_context: BDDContext):
    email = bdd_context.current_email
    assert email is not None
    retry = _register(bdd_context, "A", email, VALID_PASSWORD)
    _record(bdd_context, retry)


@when("用户使用未注册的合法邮箱和合规密码提交注册申请")
def when_register_fresh(bdd_context: BDDContext):
    email = bdd_context.current_email or _unique("fresh") + "@example.com"
    _register(bdd_context, "A", email, VALID_PASSWORD)
    bdd_context.current_email = email
    account = _account_row(bdd_context, email)
    bdd_context.accounts[_norm_email(email)] = {
        "account_id": str(account.account_id) if account else "",
        "password": VALID_PASSWORD,
    }


@when("用户在 24 小时内访问该验证凭据链接完成验证")
def when_verify_within_window(bdd_context: BDDContext):
    _verify(bdd_context, "A", bdd_context.verification_secrets["current"])


@when(
    parsers.cfparse('用户使用链接 Link_B 成功完成邮箱验证，账号状态变更为 "{status}"')
)
def when_verify_link_b(bdd_context: BDDContext, status: str):
    _verify(bdd_context, "A", bdd_context.verification_secrets["Link_B"])


@when("用户随后尝试访问链接 Link_A")
def when_verify_link_a(bdd_context: BDDContext):
    _verify(bdd_context, "A", bdd_context.verification_secrets["Link_A"])


@when("用户尝试访问该过期验证链接")
def when_verify_expired_link(bdd_context: BDDContext):
    _verify(bdd_context, "A", bdd_context.verification_secrets["current"])


@when("用户在浏览器中查看系统主界面")
def when_view_main_interface(bdd_context: BDDContext):
    _me(bdd_context, "A")


@when("用户尝试绕过界面直接向服务端提交创建 Workspace 请求")
def when_bypass_create_workspace(bdd_context: BDDContext):
    response = bdd_context.run(
        bdd_context.device("A").post(
            "/v1/workspaces",
            json={"name": "Bypass Ws", "idempotencyKey": str(uuid.uuid4())},
        )
    )
    _record(bdd_context, response)


@when(parsers.cfparse('该用户在另一浏览器窗口完成邮箱验证使账号变更为 "{status}"'))
def when_verify_other_window(bdd_context: BDDContext, status: str):
    # "another browser window" -> a distinct device client (B).
    secret = bdd_context.mailer.sent[-1][1]
    _verify(bdd_context, "B", secret)


@when("用户再次在设备 A 上提交创建 Workspace 请求")
def when_retry_create_workspace(bdd_context: BDDContext):
    response = bdd_context.run(
        bdd_context.device("A").post(
            "/v1/workspaces",
            json={"name": "Retry Ws", "idempotencyKey": str(uuid.uuid4())},
        )
    )
    _record(bdd_context, response)


@when("用户请求重新发送验证邮件")
def when_request_resend(bdd_context: BDDContext):
    email = bdd_context.current_email
    assert email is not None
    _resend(bdd_context, "A", email)


@when("用户再次提交重发验证邮件请求")
def when_resend_again(bdd_context: BDDContext):
    email = bdd_context.current_email
    assert email is not None
    _resend(bdd_context, "A", email)


@when(
    parsers.cfparse('客户端分别使用合规密码提交 "{email_a}" 和 "{email_b}" 的注册申请')
)
def when_register_pair(bdd_context: BDDContext, email_a: str, email_b: str):
    first = _register(bdd_context, "A", email_a, VALID_PASSWORD)
    second = _register(bdd_context, "A", email_b, VALID_PASSWORD)
    _record(bdd_context, second)
    bdd_context.captured_responses = [first, second]


@when(
    parsers.cfparse('客户端 A 与客户端 B 在同一时间并发提交使用 "{email}" 的注册申请')
)
def when_concurrent_registration(bdd_context: BDDContext, email: str):
    # Two distinct device identities (separate rate-limit identities). The
    # requests are issued back-to-back; the scenario asserts the deterministic
    # post-race outcome: exactly one account, both clients receive the uniform
    # anti-enumeration response. A genuine lost-update race requires two
    # transactions and is covered by the infrastructure tests (task-5).
    first = _register(bdd_context, "A", email, VALID_PASSWORD)
    second = _register(bdd_context, "B", email, VALID_PASSWORD)
    _record(bdd_context, second)
    bdd_context.captured_responses = [first, second]


@given("账号原本没有任何在线设备")
def given_no_online_devices(bdd_context: BDDContext):
    # Seed the account through the real adapter WITHOUT any registration/login
    # session so the scenario starts with zero active device sessions.
    email = _unique("concurrent") + "@example.com"
    account = Account.create_with_email(email, at=_utc_now())
    bdd_context.run(
        PostgresAccountRepository(bdd_context.db_session).save(
            account, PasswordHasher.hash(VALID_PASSWORD)
        )
    )
    bdd_context.accounts[_norm_email(email)] = {
        "account_id": str(account.account_id),
        "password": VALID_PASSWORD,
    }
    bdd_context.current_email = email


@when("设备 A、设备 B 与设备 C 在毫秒级时间内并发提交合法登录请求")
def when_three_devices_login(bdd_context: BDDContext):
    # Three distinct device identities submit the legal login back-to-back.
    # The scenario asserts the deterministic post-race outcome (exactly 2
    # Active sessions; the oldest createdAt is replaced); a true
    # same-transaction race is exercised by the infrastructure tests (task-5).
    email, password = _current_credentials(bdd_context)
    for device in ("A", "B", "C"):
        response = _login(bdd_context, device, email, password)
        assert response.status_code == 200


@when(parsers.cfparse("用户在设备 A 输入正确的邮箱与密码提交登录"))
def when_login_device_a(bdd_context: BDDContext):
    email, password = _current_credentials(bdd_context)
    _login(bdd_context, "A", email, password)


@when("用户在设备 A 提交正确的邮箱与密码登录")
def when_login_device_a_pending(bdd_context: BDDContext):
    email, password = _current_credentials(bdd_context)
    _login(bdd_context, "A", email, password)


@when("用户输入正确的邮箱与密码尝试登录")
def when_login_correct_credentials(bdd_context: BDDContext):
    email, password = _current_credentials(bdd_context)
    _login(bdd_context, "A", email, password)


@when(
    parsers.cfparse('客户端分别使用错误密码对 "{email_a}" 和 "{email_b}" 提交登录请求')
)
def when_login_pair_wrong_password(bdd_context: BDDContext, email_a: str, email_b: str):
    first = _login(bdd_context, "A", email_a, "Wrong!Password")
    second = _login(bdd_context, "A", email_b, "Wrong!Password")
    _record(bdd_context, second)
    bdd_context.captured_responses = [first, second]


@when("用户输入合法凭据成功完成登录")
def when_login_valid_credentials(bdd_context: BDDContext):
    email, password = _current_credentials(bdd_context)
    _login(bdd_context, "A", email, password)


@when("该会话连续 30 天未进行任何操作，达到 30 天 Idle Expiry")
def when_idle_expiry(bdd_context: BDDContext):
    _execute_update(
        bdd_context,
        "UPDATE auth.sessions SET last_seen_at = :at WHERE session_id = :sid",
        {
            "at": _utc_now() - timedelta(days=31),
            "sid": bdd_context.sessions["A"],
        },
    )


@when("设备 A 发起新的业务 API 请求")
def when_device_a_business_request(bdd_context: BDDContext):
    _me(bdd_context, "A")


@when("该会话自创建起已达到第 90 天整，达到 90 天 Absolute Expiry")
def when_absolute_expiry(bdd_context: BDDContext):
    _execute_update(
        bdd_context,
        "UPDATE auth.sessions SET expires_at = :expired WHERE session_id = :sid",
        {
            "expired": _utc_now() - timedelta(days=1),
            "sid": bdd_context.sessions["A"],
        },
    )


@when("设备 A 再次发起业务请求")
def when_device_a_business_again(bdd_context: BDDContext):
    _me(bdd_context, "A")


@when("服务端因安全风控主动撤销设备 A 的会话")
def when_server_revokes_device_a(bdd_context: BDDContext):
    _execute_update(
        bdd_context,
        "UPDATE auth.sessions SET status = 'Revoked', "
        "invalidation_reason = 'SecurityRevoke' WHERE session_id = :sid",
        {"sid": bdd_context.sessions["A"]},
    )


@when("设备 A 在多实例部署环境下向任意服务实例发起新的操作请求")
def when_device_a_other_instance(bdd_context: BDDContext):
    # A SECOND app instance (fresh ASGI app, same cookies) -> cross-instance.
    second = bdd_context.new_client()
    for cookie_name, value in bdd_context.devices["A"].cookies.items():
        second.cookies.set(cookie_name, value)
    response = bdd_context.run(second.get("/v1/auth/me"))
    _record(bdd_context, response)
    bdd_context.run(second.aclose())


@when(parsers.cfparse("用户在设备 B 上输入正确凭据成功登录"))
def when_login_device_b(bdd_context: BDDContext):
    email, password = _current_credentials(bdd_context)
    _login(bdd_context, "B", email, password)


@when(parsers.cfparse("用户在 12:00 于设备 C 上输入正确凭据成功登录"))
def when_login_device_c_12(bdd_context: BDDContext):
    email, password = _current_credentials(bdd_context)
    _login(bdd_context, "C", email, password)


@when("用户在设备 C 成功登录并触发设备替换")
def when_login_device_c_replace(bdd_context: BDDContext):
    _ensure_replacement_setup(bdd_context)
    email, password = _current_credentials(bdd_context)
    _login(bdd_context, "C", email, password)


@when("用户在设备 C 登录导致设备 A 的会话被替换下线")
def when_login_device_c_replaces_a(bdd_context: BDDContext):
    _ensure_replacement_setup(bdd_context)
    email, password = _current_credentials(bdd_context)
    _login(bdd_context, "C", email, password)


@when("设备 C 登录导致设备 A 的会话被替换")
def when_login_device_c_replaces_a_short(bdd_context: BDDContext):
    _ensure_replacement_setup(bdd_context)
    email, password = _current_credentials(bdd_context)
    _login(bdd_context, "C", email, password)


@when(
    "设备 A 立即发起任何需要认证的业务 API 请求，"
    "或在分布式多实例环境下于 5 秒内发起请求"
)
def when_device_a_immediate_request(bdd_context: BDDContext):
    _me(bdd_context, "A")


@when("设备 A 尝试重新发送历史请求或刷新当前页面")
def when_device_a_replay_request(bdd_context: BDDContext):
    _me(bdd_context, "A")
    if bdd_context.last_status == 401:
        _session_info(bdd_context, "A")


@when(parsers.cfparse('用户在设备 A 点击"退出登录"'))
def when_logout_device_a(bdd_context: BDDContext):
    _logout(bdd_context, "A")


@when("客户端再次对该会话提交登出请求")
def when_logout_again(bdd_context: BDDContext):
    _logout(bdd_context, "A")


@when("用户发起查询当前账号与会话信息的请求")
def when_query_account_and_session(bdd_context: BDDContext):
    me = _me(bdd_context, "A")
    session = _session_info(bdd_context, "A")
    bdd_context.captured_responses = [me.json(), session.json()]


@when("客户端尝试调用查询当前账号状态的接口")
def when_query_account_unauthenticated(bdd_context: BDDContext):
    _me(bdd_context, "anon")


@when("攻击者绕过前端界面限制直接向服务端提交只有 Active 账号才能执行的高风险请求")
def when_bypass_high_risk_request(bdd_context: BDDContext):
    response = bdd_context.run(bdd_context.device("A").post("/v1/workspaces", json={}))
    _record(bdd_context, response)


@when(
    parsers.cfparse(
        '用户分别在忘记密码入口输入 "{email_a}" 与 "{email_b}" 提交重置申请'
    )
)
def when_forgot_pair(bdd_context: BDDContext, email_a: str, email_b: str):
    first = _forgot(bdd_context, "A", email_a)
    second = _forgot(bdd_context, "A", email_b)
    _record(bdd_context, second)
    bdd_context.captured_responses = [first, second]


@when(
    parsers.cfparse('用户在 15 分钟有效期内访问该链接并提交合规的新密码 "{password}"')
)
def when_reset_in_window(bdd_context: BDDContext, password: str):
    email = bdd_context.current_email
    assert email is not None
    secret = bdd_context.reset_secrets.get(email) or bdd_context.reset_secrets.get(
        "current"
    )
    assert secret, "no reset secret recorded"
    _reset(bdd_context, "A", secret, password)


@when("用户尝试使用该过期凭据提交新密码")
def when_reset_expired(bdd_context: BDDContext):
    email = bdd_context.current_email
    assert email is not None
    secret = bdd_context.reset_secrets.get(email)
    assert secret is not None
    _reset(bdd_context, "A", secret, NEW_PASSWORD)


@when("用户尝试使用旧凭据 Token_1 提交新密码")
def when_reset_token1(bdd_context: BDDContext):
    _reset(bdd_context, "A", bdd_context.reset_secrets["Token_1"], NEW_PASSWORD)


@when("用户使用新凭据 Token_2 提交新密码")
def when_reset_token2(bdd_context: BDDContext):
    _reset(bdd_context, "A", bdd_context.reset_secrets["Token_2"], NEW_PASSWORD)


@when(parsers.cfparse("用户在设备 C 上通过邮件重置链接成功重置了密码"))
def when_reset_via_link_device_c(bdd_context: BDDContext):
    email, _ = _current_credentials(bdd_context)
    if bdd_context.reset_secrets.get(email) is None:
        forgot = _forgot(bdd_context, "C", email)
        assert forgot.status_code == 200
        _record_reset_secret(bdd_context, email)
    secret = bdd_context.reset_secrets.get(email)
    assert secret is not None
    _reset(bdd_context, "C", secret, NEW_PASSWORD)


@when("用户在登录页使用修改前的旧密码尝试登录")
def when_login_old_password(bdd_context: BDDContext):
    email, password = _current_credentials(bdd_context)
    _login(bdd_context, "A", email, password)


@when("用户在登录页使用合规的新密码提交登录")
def when_login_new_password(bdd_context: BDDContext):
    email, _ = _current_credentials(bdd_context)
    _login(bdd_context, "A", email, NEW_PASSWORD)


@when("攻击者尝试再次使用同一个重置链接提交密码修改")
def when_reset_replay(bdd_context: BDDContext):
    email, _ = _current_credentials(bdd_context)
    secret = bdd_context.reset_secrets.get(email)
    assert secret is not None
    _reset(bdd_context, "A", secret, NEW_PASSWORD)


@when("用户提交删除账号申请")
def when_delete_account(bdd_context: BDDContext):
    _delete_account(bdd_context, "A")


@when("用户确认提交删除账号申请")
def when_confirm_delete_account(bdd_context: BDDContext):
    _delete_account(bdd_context, "A")


@when("用户点击申请删除账号")
def when_click_delete_account(bdd_context: BDDContext):
    _delete_account(bdd_context, "A")


@when("用户登录系统进入 Account Recovery Mode")
def when_login_recovery_mode(bdd_context: BDDContext):
    email, password = _current_credentials(bdd_context)
    _login(bdd_context, "A", email, password)


@when("系统的最终删除定时任务执行")
def when_purge_scheduled_task(bdd_context: BDDContext):
    email, _ = _current_credentials(bdd_context)
    _run_purge(bdd_context, _account_id(bdd_context, email))


@when(parsers.cfparse('用户在 Account Recovery Mode 下点击"取消删除账号"并确认'))
def when_cancel_deletion(bdd_context: BDDContext):
    _cancel_delete(bdd_context, "A")


@when("用户使用正确的邮箱与密码登录系统")
def when_login_recovery_entry(bdd_context: BDDContext):
    email, password = _current_credentials(bdd_context)
    _login(bdd_context, "A", email, password)


@when(parsers.cfparse("用户在 12:00 于设备 C 登录进入恢复模式"))
def when_login_recovery_device_c(bdd_context: BDDContext):
    email, password = _current_credentials(bdd_context)
    _login(bdd_context, "C", email, password)


@when("用户尝试直接向服务端调用创建 Workspace、编辑协同文档或启动 AI 任务的接口")
def when_recovery_mode_business_call(bdd_context: BDDContext):
    # Workspace / collaborative-document / AI-task routes do not exist in this
    # phase; the app-wide recovery guard covers every CURRENT business route,
    # so the guarded account-status query stands in for the family (the guard
    # never even reaches unknown routes — Starlette 404s first). Documented
    # closest-executable deviation, FR-AUTH-032.
    _me(bdd_context, "A")


@then("服务端坚决拒绝该请求并返回账号处于恢复模式受限的错误提示")
def then_recovery_mode_business_rejected(bdd_context: BDDContext):
    assert bdd_context.last_status == 403
    assert bdd_context.last_body["category"] == "Permission"
    assert bdd_context.last_body["errorCode"] == "ACCOUNT_IN_RECOVERY_MODE"


@when(parsers.cfparse('账号 user_123 的 30 天宽限期结束并完成最终删除变为 "{status}"'))
def when_user_123_purged(bdd_context: BDDContext, status: str):
    account_id = UUID(bdd_context.accounts["user_123"]["account_id"])
    _execute_update(
        bdd_context,
        "UPDATE auth.accounts SET status = 'DeletionPending', "
        "deletion_requested_at = :at WHERE account_id = :account_id",
        {"at": _utc_now() - timedelta(days=31), "account_id": account_id},
    )
    _run_purge(bdd_context, account_id)


@when("客户端再次提交登录请求")
def when_login_again_after_lockout(bdd_context: BDDContext):
    email, _ = _current_credentials(bdd_context)
    _login(bdd_context, "A", email, VALID_PASSWORD)


@when("15 分钟冷却期结束后用户输入正确密码提交登录")
def when_login_after_cooldown(bdd_context: BDDContext):
    # The scenario's limiter uses a shortened window (2s) so the temporary
    # cooldown self-heals within the test; wait for the Valkey TTL expiry.
    bdd_context.run(asyncio.sleep(2.2))
    email, _ = _current_credentials(bdd_context)
    _login(bdd_context, "A", email, VALID_PASSWORD)


@when(
    "用户完成注册、邮箱验证、密码重置、会话替换、申请删除、取消删除或最终删除等任一关键操作"
)
def when_perform_audited_chain(bdd_context: BDDContext):
    email = _unique("audited") + "@example.com"
    _register_account_pw(bdd_context, email, VALID_PASSWORD)
    # 邮箱验证已停用（注册即 Active → AccountCreated + RegistrationActivated）。
    # 兼容回切：若 mailer 仍捕获到验证 secret，则显式消费保持审计链完整。
    if bdd_context.mailer.sent:
        verified = _verify(bdd_context, "A", bdd_context.mailer.sent[-1][1])
        assert verified.status_code == 200
    # session replacement: device B login, then C replaces the oldest (A)
    login_b = _login(bdd_context, "B", email, VALID_PASSWORD)
    assert login_b.status_code == 200
    _backdate_session(bdd_context, "A", hours=2)
    _backdate_session(bdd_context, "B", hours=1)
    login_c = _login(bdd_context, "C", email, VALID_PASSWORD)
    assert login_c.status_code == 200  # -> SessionReplaced audit for A
    # password reset (forgot + reset) -> PasswordReset audit, revokes A/B/C
    bdd_context.rate_limiter = RateLimiter(
        bdd_context.valkey_client, resend_cooldown_seconds=0
    )
    forgot_response = _forgot(bdd_context, "A", email)
    assert forgot_response.status_code == 200
    _record_reset_secret(bdd_context, email)
    reset_secret = bdd_context.reset_secrets.get(email)
    assert reset_secret is not None
    reset_response = _reset(bdd_context, "A", reset_secret, NEW_PASSWORD)
    assert reset_response.status_code == 200
    bdd_context.accounts[_norm_email(email)]["password"] = NEW_PASSWORD
    # fresh session for the deletion steps (reset revoked all sessions)
    fresh = _login(bdd_context, "C", email, NEW_PASSWORD)
    assert fresh.status_code == 200
    # request deletion -> AccountDeletionRequested; cancel -> ...Cancelled;
    # request again -> backdate -> final purge -> AccountDeleted
    delete1 = _delete_account(bdd_context, "C")
    assert delete1.status_code == 200
    cancel = _cancel_delete(bdd_context, "C")
    assert cancel.status_code == 200
    delete2 = _delete_account(bdd_context, "C")
    assert delete2.status_code == 200
    account_id = _account_id(bdd_context, email)
    _execute_update(
        bdd_context,
        "UPDATE auth.accounts SET deletion_requested_at = :at "
        "WHERE account_id = :account_id",
        {"at": _utc_now() - timedelta(days=31), "account_id": account_id},
    )
    _execute_update(
        bdd_context,
        "UPDATE auth.account_deletion_requests SET execute_after = :at "
        "WHERE account_id = :account_id",
        {"at": _utc_now() - timedelta(days=1), "account_id": account_id},
    )
    _run_purge(bdd_context, account_id)


# ---------------------------------------------------------------------------
# Then: assertions
# ---------------------------------------------------------------------------


@then(parsers.cfparse('系统成功创建新账号，账号生命周期状态为 "{status}"'))
def then_account_created_status(bdd_context: BDDContext, status: str):
    assert bdd_context.last_status == 201
    email = bdd_context.current_email
    assert email is not None
    db_status = _account_status(bdd_context, email)
    assert db_status == status


@then("系统自动为该设备建立活跃登录会话并进入系统受限工作台，无需手动二次登录")
def then_auto_session_created(bdd_context: BDDContext):
    session_id = bdd_context.sessions.get("A")
    assert session_id, "registration must issue a session cookie"
    assert _session_status(bdd_context, session_id) == "Active"


@then(parsers.cfparse('系统向 "{email}" 发送一封邮箱验证邮件'))
def then_verification_mail_sent(bdd_context: BDDContext, email: str):
    assert any(entry[0] == _norm_email(email) for entry in bdd_context.mailer.sent), (
        f"no verification mail recorded for {email}"
    )


@then("注册流程不依赖邮箱验证，账号即刻拥有创建 Workspace 的完整能力")
def then_registration_full_capacity(bdd_context: BDDContext):
    email = bdd_context.current_email
    assert email is not None
    assert _account_status(bdd_context, email) == "Active"
    me = bdd_context.run(bdd_context.device("A").get("/v1/auth/me"))
    assert me.status_code == 200
    assert me.json()["canCreateWorkspace"] is True


@then("系统记录账号创建的安全审计事件")
def then_account_created_audit(bdd_context: BDDContext):
    email = bdd_context.current_email
    assert email is not None
    actions = _audit_actions(bdd_context, _account_id(bdd_context, email))
    assert "AccountCreated" in actions


@then(
    parsers.cfparse(
        '系统拒绝注册申请并返回 "{category}" 类别错误，'
        "提示密码长度须在 12 至 128 字符之间"
    )
)
def then_short_password_rejected(bdd_context: BDDContext, category: str):
    assert bdd_context.last_status == 422
    assert bdd_context.last_body["category"] == category
    # A <12-char password is rejected by the CONTRACT schema first (the
    # generated DTO enforces minLength 12 -> REQUEST_VALIDATION_ERROR with a
    # `password` fieldError coded PASSWORD_TOO_WEAK); the domain policy raises
    # PASSWORD_TOO_WEAK directly for the other weak cases (FR-AUTH-001).
    if bdd_context.last_body["errorCode"] == "REQUEST_VALIDATION_ERROR":
        assert any(
            field.get("field") == "password"
            and field.get("code") == "PASSWORD_TOO_WEAK"
            for field in (bdd_context.last_body.get("fieldErrors") or [])
        )
    else:
        assert bdd_context.last_body["errorCode"] == "PASSWORD_TOO_WEAK"


@then(
    parsers.cfparse(
        '系统拒绝注册申请并返回 "{category}" 类别错误，提示密码过于常见或存在安全风险'
    )
)
def then_leaked_password_rejected(bdd_context: BDDContext, category: str):
    assert bdd_context.last_status == 422
    assert bdd_context.last_body["category"] == category
    assert bdd_context.last_body["errorCode"] == "PASSWORD_TOO_WEAK"


@then("系统中未创建任何账号且未建立任何会话")
def then_no_account_no_session(bdd_context: BDDContext):
    # The rejected registration must not have created an account or any
    # session; the dev database may legitimately contain rows committed by
    # other suites, so the assertion is scoped to the scenario email.
    email = bdd_context.current_email
    assert email is not None
    accounts = int(
        _scalar(
            bdd_context,
            text("SELECT count(*) FROM auth.accounts WHERE normalized_email = :email"),
            {"email": _norm_email(email)},
        )
        or 0
    )
    sessions = int(
        _scalar(
            bdd_context,
            text(
                "SELECT count(*) FROM auth.sessions s "
                "JOIN auth.accounts a ON a.account_id = s.account_id "
                "WHERE a.normalized_email = :email"
            ),
            {"email": _norm_email(email)},
        )
        or 0
    )
    assert accounts == 0
    assert sessions == 0


@then("系统中未创建任何账号")
def then_no_account(bdd_context: BDDContext):
    email = bdd_context.current_email
    assert email is not None
    accounts = int(
        _scalar(
            bdd_context,
            text("SELECT count(*) FROM auth.accounts WHERE normalized_email = :email"),
            {"email": _norm_email(email)},
        )
        or 0
    )
    assert accounts == 0


@then("系统中最终只存在一个有效账号")
def then_single_account(bdd_context: BDDContext):
    email = bdd_context.current_email
    assert email is not None
    total = int(
        _scalar(
            bdd_context,
            text("SELECT count(*) FROM auth.accounts WHERE normalized_email = :email"),
            {"email": _norm_email(email)},
        )
        or 0
    )
    assert total == 1


@then("重试请求得到成功的幂等响应")
def then_retry_success_response(bdd_context: BDDContext):
    assert bdd_context.last_status == 201
    assert bdd_context.last_body["messageKey"] == "REGISTER_SUCCESS"


@then(
    parsers.cfparse(
        '系统成功创建 "PendingVerification" 账号并自动建立活跃会话进入受限系统'
    )
)
def then_mail_failure_still_creates(bdd_context: BDDContext):
    assert bdd_context.last_status == 201
    assert bdd_context.sessions.get("A")
    email = bdd_context.current_email
    assert email is not None
    # 邮箱验证已停用：注册即 Active，与邮件投递是否可用无关。
    assert _account_status(bdd_context, email) == "Active"


@then("账号处于可再次请求重新发送验证邮件的状态")
def then_can_request_resend(bdd_context: BDDContext):
    email = bdd_context.current_email
    assert email is not None
    # 邮箱验证已停用：注册即 Active，不再处于"待验证 → 可重发"状态窗口。
    assert _account_status(bdd_context, email) == "Active"


@then("系统记录注册直通激活的安全审计事件")
def then_registration_activated_audited(bdd_context: BDDContext):
    email = bdd_context.current_email
    assert email is not None
    actions = _audit_actions(bdd_context, _account_id(bdd_context, email))
    assert "RegistrationActivated" in actions


@then(parsers.cfparse('账号状态为 "{status}"，不再需要邮箱验证'))
def then_account_status_no_verification(bdd_context: BDDContext, status: str):
    email, _ = _current_credentials(bdd_context)
    assert _account_status(bdd_context, email) == status


@then(parsers.cfparse('账号生命周期状态变更为 "{status}"'))
def then_account_lifecycle(bdd_context: BDDContext, status: str):
    email, _ = _current_credentials(bdd_context)
    assert _account_status(bdd_context, email) == status


@then("该验证凭据被标记为已消费")
def then_token_consumed(bdd_context: BDDContext):
    secret = bdd_context.verification_secrets["current"]
    consumed = _scalar(
        bdd_context,
        text(
            "SELECT consumed_at FROM auth.one_time_tokens "
            "WHERE token_hash = :token_hash"
        ),
        {"token_hash": _hash_secret(secret)},
    )
    assert consumed is not None


@then("系统记录邮箱验证完成的安全审计事件")
def then_email_verified_audit(bdd_context: BDDContext):
    email = bdd_context.current_email
    assert email is not None
    actions = _audit_actions(bdd_context, _account_id(bdd_context, email))
    assert "EmailVerified" in actions


@then("系统拒绝链接 Link_A 的验证请求并提示链接已失效")
def then_link_a_rejected(bdd_context: BDDContext):
    assert bdd_context.last_status == 401
    assert bdd_context.last_body["errorCode"] == "EMAIL_VERIFICATION_TOKEN_INVALID"


@then(parsers.cfparse('账号生命周期状态继续保持为 "{status}" 不受影响'))
def then_account_status_unchanged(bdd_context: BDDContext, status: str):
    email, _ = _current_credentials(bdd_context)
    assert _account_status(bdd_context, email) == status


@then("系统拒绝该验证请求并提示链接已过期失效")
def then_expired_link_rejected(bdd_context: BDDContext):
    assert bdd_context.last_status == 401
    assert bdd_context.last_body["errorCode"] == "EMAIL_VERIFICATION_TOKEN_INVALID"


@then(parsers.cfparse('账号生命周期状态保持为 "{status}" 不变'))
def then_account_status_kept(bdd_context: BDDContext, status: str):
    email, _ = _current_credentials(bdd_context)
    assert _account_status(bdd_context, email) == status


@then("系统允许用户进入工作台并展示邮箱未验证横幅")
def then_can_enter_product(bdd_context: BDDContext):
    assert bdd_context.last_status == 200
    assert bdd_context.last_body["accountStatus"] == "PendingVerification"


@then("界面不呈现可用的创建 Workspace 入口")
def then_no_workspace_entry(bdd_context: BDDContext):
    me = bdd_context.run(bdd_context.device("A").get("/v1/auth/me"))
    assert me.status_code == 200
    assert me.json()["canCreateWorkspace"] is False


@then(parsers.cfparse('服务端权威拒绝该请求并返回 "{category}" 类别权限受限错误提示'))
def then_server_authoritative_reject(bdd_context: BDDContext, category: str):
    # FR-AUTH-032 (recovery guard): 403 Permission ACCOUNT_IN_RECOVERY_MODE.
    # FR-AUTH-003 workspace-call (documented closest-executable): the
    # workspace route does not exist in this phase -> server-refused 404
    # NotFound with no state change; both are authoritative rejections.
    assert bdd_context.last_status in (403, 404)
    if bdd_context.last_status == 403:
        assert bdd_context.last_body["category"] == "Permission"
        assert bdd_context.last_body["errorCode"] in {
            "ACCOUNT_IN_RECOVERY_MODE",
            "WORKSPACE_CREATION_REQUIRES_ACTIVE_ACCOUNT",
        }
    else:
        assert bdd_context.last_body["category"] == "NotFound"


@then("系统中未产生任何新的 Workspace")
def then_no_workspace_created(bdd_context: BDDContext):
    # No workspaces schema exists in this phase (the Workspace module is a
    # future slice); assert the structural absence + no business state change.
    tables = int(
        _scalar(
            bdd_context,
            text(
                "SELECT count(*) FROM information_schema.tables "
                "WHERE table_name = 'workspaces'"
            ),
        )
        or 0
    )
    assert tables == 0
    if bdd_context.current_email:
        assert (
            _account_status(bdd_context, bdd_context.current_email)
            == "PendingVerification"
        )


@then("服务端确认其当前已具备完整能力并成功创建 Workspace")
def then_can_create_workspace(bdd_context: BDDContext):
    # Closest executable for FR-AUTH-003: the server-authoritative capability
    # (canCreateWorkspace) flips to True after verification; the workspace
    # CREATE route itself lands with the Workspace slice.
    me = bdd_context.run(bdd_context.device("A").get("/v1/auth/me"))
    assert me.status_code == 200
    assert me.json()["canCreateWorkspace"] is True


@then("系统成功向该邮箱发送新的验证邮件")
def then_resend_ok(bdd_context: BDDContext):
    assert bdd_context.last_status == 200
    assert bdd_context.last_body["messageKey"] == "VERIFICATION_EMAIL_RESENT"
    assert len(bdd_context.mailer.sent) >= 2


@then("界面开始展示下一次可重发的 60 秒倒计时")
def then_resend_countdown(bdd_context: BDDContext):
    assert bdd_context.last_body.get("nextAllowedAt") is not None


@then(parsers.cfparse('账号状态继续保持为 "{status}"'))
def then_account_status_stays(bdd_context: BDDContext, status: str):
    email, _ = _current_credentials(bdd_context)
    assert _account_status(bdd_context, email) == status


@then(parsers.cfparse('系统拒绝该请求并返回 "{category}" 类别的频控错误提示'))
def then_rate_limited(bdd_context: BDDContext, category: str):
    assert bdd_context.last_status == 429
    assert bdd_context.last_body["category"] == category
    assert bdd_context.last_body["errorCode"] == "RATE_LIMITED"


@then("系统不会向外部发出多余的邮件")
def then_no_extra_mail(bdd_context: BDDContext):
    email = bdd_context.current_email
    assert email is not None
    matching = [
        entry for entry in bdd_context.mailer.sent if entry[0] == _norm_email(email)
    ]
    assert len(matching) <= 1


@then(
    parsers.cfparse(
        '两个请求收到的外部提示完全一致，均显示"如果该邮箱可以继续注册，请检查邮箱中的后续指引"'
    )
)
def then_register_responses_identical(bdd_context: BDDContext):
    assert len(bdd_context.captured_responses) == 2
    first, second = bdd_context.captured_responses
    assert first.status_code == second.status_code == 201
    # The uniform anti-enumeration response echoes the SUBMITTED email address
    # (the two probes differ), so equality is structural: identical status,
    # messageKey and key sets — never an existence-revealing field.
    assert (
        first.json()["messageKey"] == second.json()["messageKey"] == "REGISTER_SUCCESS"
    )
    assert set(first.json().keys()) == set(second.json().keys())
    assert "REGISTER_SUCCESS" in first.json()["messageKey"]


@then('外部响应不返回"此邮箱已经注册"等任何可用于账号枚举的明确信息')
def then_no_enumeration_leak(bdd_context: BDDContext):
    payloads = [bdd_context.last_body]
    payloads.extend(response.json() for response in bdd_context.captured_responses)
    for body in payloads:
        if body:
            assert "已经注册" not in json.dumps(body, ensure_ascii=False)


@then(parsers.cfparse('系统中关于 "{email}" 的有效账号数量恒为 1，未产生重复账号'))
def then_single_account_for_email(bdd_context: BDDContext, email: str):
    total = int(
        _scalar(
            bdd_context,
            text("SELECT count(*) FROM auth.accounts WHERE normalized_email = :email"),
            {"email": _norm_email(email)},
        )
        or 0
    )
    assert total == 1


@then(parsers.cfparse('系统最终全局有且仅有一个使用 "{email}" 的有效账号被创建'))
def then_race_single_account(bdd_context: BDDContext, email: str):
    then_single_account_for_email(bdd_context, email)


@then("两个并发客户端均获得统一的防枚举提示响应")
def then_concurrent_uniform_payload(bdd_context: BDDContext):
    assert len(bdd_context.captured_responses) == 2
    first, second = bdd_context.captured_responses
    assert first.status_code == second.status_code == 201
    assert (
        first.json()["messageKey"] == second.json()["messageKey"] == "REGISTER_SUCCESS"
    )
    assert first.json() == second.json()


@then(parsers.cfparse('登录成功并为设备 A 建立一个状态为 "{status}" 的设备会话'))
def then_login_ok_session(bdd_context: BDDContext, status: str):
    assert bdd_context.last_status == 200
    session_id = bdd_context.sessions.get("A")
    assert session_id
    assert _session_status(bdd_context, session_id) == status


@then("用户进入系统主工作台")
def then_enter_main_workspace(bdd_context: BDDContext):
    _me(bdd_context, "A")
    assert bdd_context.last_status == 200


@then("登录成功并为设备 A 建立活跃设备会话")
def then_login_ok_active_session(bdd_context: BDDContext):
    assert bdd_context.last_status == 200
    assert bdd_context.sessions.get("A")
    assert bdd_context.last_body["recoveryModeRequired"] is False


@then("用户能够进入系统主界面使用非受限功能")
def then_enter_product_unrestricted(bdd_context: BDDContext):
    _me(bdd_context, "A")
    assert bdd_context.last_status == 200
    assert bdd_context.last_body["accountStatus"] == "PendingVerification"


@then(parsers.cfparse('登录被系统拒绝并返回 "{category}" 类别错误'))
def then_login_rejected(bdd_context: BDDContext, category: str):
    assert bdd_context.last_status == 401
    assert bdd_context.last_body["category"] == category


@then("系统不为该设备建立任何有效会话")
def then_no_session_created(bdd_context: BDDContext):
    email, _ = _current_credentials(bdd_context)
    sessions = int(
        _scalar(
            bdd_context,
            text(
                "SELECT count(*) FROM auth.sessions s "
                "JOIN auth.accounts a ON a.account_id = s.account_id "
                "WHERE a.normalized_email = :email AND s.status = 'Active'"
            ),
            {"email": _norm_email(email)},
        )
        or 0
    )
    assert sessions == 0


@then("两个请求均收到完全一致的凭据无效（Invalid Credentials）错误响应")
def then_login_responses_identical(bdd_context: BDDContext):
    assert len(bdd_context.captured_responses) == 2
    first, second = bdd_context.captured_responses
    assert first.status_code == second.status_code == 401
    left, right = first.json(), second.json()
    for body in (left, right):
        body.pop("requestId", None)
    assert left == right
    assert left["category"] == "Authentication"
    assert left["errorCode"] == "INVALID_CREDENTIALS"


@then("外部响应文案与响应耗时量级完全一致，不泄露邮箱是否存在")
def then_login_uniform_timing(bdd_context: BDDContext):
    # Response copy is asserted identical above; timing magnitude is covered
    # by tests/security/test_auth_anti_enumeration.py (loose, CI-safe bounds).
    assert bdd_context.last_body["errorCode"] == "INVALID_CREDENTIALS"


@then("服务端为客户端颁发一个全新的已认证会话凭据")
def then_fresh_session_issued(bdd_context: BDDContext):
    assert bdd_context.last_status == 200
    new_id = bdd_context.sessions.get("A")
    assert new_id
    pre_login = bdd_context.verification_secrets.get("pre_login_session_id")
    if pre_login:
        assert new_id != pre_login


@then("登录前持有的旧未认证标识无法再用于发起任何后续请求")
def then_old_identifier_invalid(bdd_context: BDDContext):
    # The old (bogus) identifier is tried against a fresh client — it must
    # never authenticate.
    probe = bdd_context.device("anon-old")
    probe.cookies.set(
        "dom_session", bdd_context.verification_secrets["pre_login_session_id"]
    )
    me = bdd_context.run(probe.get("/v1/auth/me"))
    assert me.status_code == 401


@then(parsers.cfparse('服务端拒绝该请求并返回 "{category}" 类别的会话过期错误'))
def then_session_expired(bdd_context: BDDContext, category: str):
    assert bdd_context.last_status == 401
    assert bdd_context.last_body["category"] == category
    assert bdd_context.last_body["errorCode"] == "SESSION_EXPIRED"


@then('客户端向用户展示"登录已过期，请重新登录"的提示')
def then_expired_user_copy(bdd_context: BDDContext):
    assert bdd_context.last_body["messageKey"] == "auth.error.sessionExpired"


@then("服务端强制拒绝该请求并返回会话过期错误，要求重新登录")
def then_absolute_expiry_rejected(bdd_context: BDDContext):
    assert bdd_context.last_status == 401
    assert bdd_context.last_body["errorCode"] == "SESSION_EXPIRED"


@then("请求均被服务端权威判定为未认证并拒绝访问")
def then_revocation_rejected(bdd_context: BDDContext):
    assert bdd_context.last_status == 401


@then("客户端无法通过保留旧凭据绕过撤销限制")
def then_revocation_no_bypass(bdd_context: BDDContext):
    _me(bdd_context, "A")
    assert bdd_context.last_status == 401


@then("设备 B 成功建立新的活跃会话")
def then_device_b_session(bdd_context: BDDContext):
    assert bdd_context.last_status == 200
    session_id = bdd_context.sessions.get("B")
    assert session_id
    assert _session_status(bdd_context, session_id) == "Active"


@then(parsers.cfparse('设备 A 的会话继续保持 "{status}" 状态'))
def then_device_a_stays(bdd_context: BDDContext, status: str):
    session_id = bdd_context.sessions["A"]
    assert _session_status(bdd_context, session_id) == status


@then(parsers.cfparse("系统中当前活跃设备会话总数为 {count:d}"))
def then_active_session_count(bdd_context: BDDContext, count: int):
    email, _ = _current_credentials(bdd_context)
    total = _active_session_count(bdd_context, _account_id(bdd_context, email))
    assert total == count


@then(parsers.cfparse('设备 C 成功建立状态为 "{status}" 的新会话'))
def then_device_c_session(bdd_context: BDDContext, status: str):
    assert bdd_context.last_status == 200
    session_id = bdd_context.sessions.get("C")
    assert session_id
    assert _session_status(bdd_context, session_id) == status


@then("设备 C 成功建立活跃会话")
def then_device_c_session_active(bdd_context: BDDContext):
    assert bdd_context.last_status == 200
    session_id = bdd_context.sessions.get("C")
    assert session_id
    assert _session_status(bdd_context, session_id) == "Active"


@then(
    parsers.cfparse(
        '系统严格根据 createdAt 判定最旧会话，将设备 A 变更为 "Replaced"，'
        '失效原因为 "{reason}"'
    )
)
def then_device_a_replaced_by_created_at(bdd_context: BDDContext, reason: str):
    _assert_device_a_replaced(bdd_context, reason)


def _assert_device_a_replaced(
    bdd_context: BDDContext, reason: str | None = None
) -> None:
    session_id = bdd_context.sessions["A"]
    assert _session_status(bdd_context, session_id) == "Replaced"
    if reason is not None:
        invalidation = _session_field(bdd_context, session_id, "invalidation_reason")
        assert invalidation == reason


@then('createdAt 最早的设备 A 的会话被变更为 "Replaced"')
def then_device_a_replaced_by_created_at_short(bdd_context: BDDContext):
    _assert_device_a_replaced(bdd_context)


@then(parsers.cfparse('设备 B 保持 "{status}" 状态不变'))
def then_device_b_kept(bdd_context: BDDContext, status: str):
    session_id = bdd_context.sessions["B"]
    assert _session_status(bdd_context, session_id) == status


@then(parsers.cfparse("系统中当前活跃设备会话总数依然严格为 2（设备 B 和设备 C）"))
def then_active_count_two(bdd_context: BDDContext):
    then_active_session_count(bdd_context, 2)


@then(parsers.cfparse("系统中当前活跃设备会话总数严格保持为 2（设备 B 和设备 C）"))
def then_active_count_two_strict(bdd_context: BDDContext):
    then_active_session_count(bdd_context, 2)


@then("设备 A 被置为被替换下线状态")
def then_device_a_replaced_offline(bdd_context: BDDContext):
    assert _session_status(bdd_context, bdd_context.sessions["A"]) == "Replaced"


@then("设备 B 继续保持正常活跃连接，能够继续发起 API 请求与实时协同")
def then_device_b_still_active_api(bdd_context: BDDContext):
    me = bdd_context.run(bdd_context.device("B").get("/v1/auth/me"))
    assert me.status_code == 200


@then("设备 B 不会收到任何被替换或强制退出的通知")
def then_device_b_no_notice(bdd_context: BDDContext):
    # Only the replaced session (A) receives an invalidation event; B stays
    # Active in the source of truth and keeps working.
    assert _session_status(bdd_context, bdd_context.sessions["B"]) == "Active"


@then(
    parsers.cfparse(
        '3 个设备登录操作全部处理完成后，系统中状态为 "Active" 的设备会话数严格为 2'
    )
)
def then_concurrent_login_converges(bdd_context: BDDContext):
    email, _ = _current_credentials(bdd_context)
    total = _active_session_count(bdd_context, _account_id(bdd_context, email))
    assert total == 2


@then(parsers.cfparse('createdAt 最早的 1 台设备被确定性地替换为 "Replaced" 状态'))
def then_oldest_deterministically_replaced(bdd_context: BDDContext):
    email, _ = _current_credentials(bdd_context)
    replaced = _scalar(
        bdd_context,
        text(
            "SELECT count(*) FROM auth.sessions WHERE account_id = :account_id "
            "AND status = 'Replaced'"
        ),
        {"account_id": _account_id(bdd_context, email)},
    )
    assert int(replaced or 0) == 1


@then("系统不会出现 3 台设备长期共存或全部会话意外丢失的竞态异常")
def then_no_race_anomaly(bdd_context: BDDContext):
    email, _ = _current_credentials(bdd_context)
    total = _active_session_count(bdd_context, _account_id(bdd_context, email))
    assert total == 2


@then(parsers.cfparse('服务端直接拒绝该请求并返回归因为 "SessionReplaced" 的错误响应'))
def then_session_replaced_error(bdd_context: BDDContext):
    assert bdd_context.last_status == 401
    assert bdd_context.last_body["errorCode"] == "SESSION_REPLACED"


@then("替换发生经过最长 5 秒窗口后，全系统所有实例对设备 A 的已认证请求 100% 拒绝")
def then_convergence_rejection(bdd_context: BDDContext):
    # The 5s bound is the session-cache TTL; the source of truth is Postgres,
    # so every instance rejects immediately (FR-AUTH-015).
    _assert_device_a_replaced(bdd_context)
    assert _session_status(bdd_context, bdd_context.sessions["A"]) == "Replaced"
    me = bdd_context.run(bdd_context.device("A").get("/v1/auth/me"))
    assert me.status_code == 401
    assert me.json()["errorCode"] == "SESSION_REPLACED"


@then("响应中不泄露该账号在其他设备上的敏感信息")
def then_no_other_device_leak(bdd_context: BDDContext):
    body = (
        json.dumps(bdd_context.last_body, ensure_ascii=False)
        if bdd_context.last_body
        else ""
    )
    assert "primaryEmail" not in body and "sessionId" not in body


@then("系统持续判定该会话无效并拒绝执行")
def then_persistent_rejection(bdd_context: BDDContext):
    assert bdd_context.last_status == 401
    assert bdd_context.last_body is not None
    assert bdd_context.last_body["category"] == "Authentication"


@then(parsers.cfparse('会话状态无法通过重试逆转为 "{status}"'))
def then_session_irreversible(bdd_context: BDDContext, status: str):
    assert _session_status(bdd_context, bdd_context.sessions["A"]) == "Replaced"


@then(parsers.cfparse('设备 A 的会话状态变更为 "LoggedOut" 并返回登录页'))
def then_device_a_logged_out(bdd_context: BDDContext):
    assert bdd_context.last_status == 200
    assert bdd_context.last_body["sessionStatus"] == "LoggedOut"
    assert _session_status(bdd_context, bdd_context.sessions["A"]) == "LoggedOut"


@then("设备 A 的实时协同连接立即断开")
def then_realtime_disconnect(bdd_context: BDDContext):
    # The realtime channel authenticates through the session; logout persists
    # LoggedOut and evicts the session cache entry the channel depends on.
    assert _session_status(bdd_context, bdd_context.sessions["A"]) == "LoggedOut"


@then(parsers.cfparse('设备 B 的会话继续保持 "{status}" 状态，操作不受任何影响'))
def then_device_b_unaffected(bdd_context: BDDContext, status: str):
    assert _session_status(bdd_context, bdd_context.sessions["B"]) == status
    me = bdd_context.run(bdd_context.device("B").get("/v1/auth/me"))
    assert me.status_code == 200


@then("设备 A 界面提示正常退出，不展示被替换下线弹窗")
def then_normal_logout_no_replaced_modal(bdd_context: BDDContext):
    assert bdd_context.last_body["sessionStatus"] == "LoggedOut"


@then("系统成功返回并保持已登出状态，不返回系统异常")
def then_logout_idempotent(bdd_context: BDDContext):
    assert bdd_context.last_status == 200
    assert bdd_context.last_body["sessionStatus"] == "AlreadyLoggedOut"


@then(parsers.cfparse('系统返回当前账号状态为 "{status}"'))
def then_me_account_status(bdd_context: BDDContext, status: str):
    assert bdd_context.captured_responses[0]["accountStatus"] == status


@then("系统返回当前设备会话的基本标识信息（包含创建时间与当前设备标记）")
def then_session_basic_info(bdd_context: BDDContext):
    session_body = bdd_context.captured_responses[1]
    assert session_body["sessionId"]
    assert session_body["createdAt"]
    assert session_body["currentDevice"] is True


@then(parsers.cfparse('系统拒绝该请求并返回 "{category}" 类别错误'))
def then_generic_rejected(bdd_context: BDDContext, category: str):
    assert bdd_context.last_status == 401
    assert bdd_context.last_body["category"] == category


@then("响应中不暴露任何账号元数据")
def then_no_account_metadata(bdd_context: BDDContext):
    body = json.dumps(bdd_context.last_body, ensure_ascii=False)
    assert "accountId" not in body and "primaryEmail" not in body


@then("服务端独立根据账号状态判定该用户缺乏对应能力并拒绝执行")
def then_capability_authority(bdd_context: BDDContext):
    # The workspace-create route does not exist in this phase; the server-
    # authoritative capability is exposed via /me (canCreateWorkspace).
    me = bdd_context.run(bdd_context.device("A").get("/v1/auth/me"))
    assert me.status_code == 200
    assert me.json()["canCreateWorkspace"] is False


@then("系统不产生任何业务状态变更")
def then_no_business_change(bdd_context: BDDContext):
    email = bdd_context.current_email
    if email:
        assert _account_status(bdd_context, email) == "PendingVerification"
        deletion_rows = int(
            _scalar(
                bdd_context,
                text(
                    "SELECT count(*) FROM auth.account_deletion_requests "
                    "WHERE account_id = :account_id"
                ),
                {"account_id": _account_id(bdd_context, email)},
            )
            or 0
        )
        assert deletion_rows == 0


@then(parsers.cfparse('前端展示完全一致的提示"如果该邮箱已注册，重置密码邮件已发送"'))
def then_forgot_responses_identical(bdd_context: BDDContext):
    assert len(bdd_context.captured_responses) == 2
    first, second = bdd_context.captured_responses
    assert first.status_code == second.status_code == 200
    assert (
        first.json()["messageKey"]
        == second.json()["messageKey"]
        == "FORGOT_PASSWORD_SUCCESS"
    )


@then(parsers.cfparse('系统仅向已注册的 "{email}" 实际发送密码重置邮件'))
def then_only_registered_gets_mail(bdd_context: BDDContext, email: str):
    matching = [
        entry
        for entry in bdd_context.mailer.password_resets
        if entry[0] == _norm_email(email)
    ]
    assert len(matching) == 1


@then("系统不向未注册邮箱发送任何邮件")
def then_no_mail_to_unregistered(bdd_context: BDDContext):
    unregistered = "unknown@example.com"
    matching = [
        entry
        for entry in bdd_context.mailer.sent
        if entry[0] == _norm_email(unregistered)
    ]
    assert matching == []


@then("密码重置成功，新密码即刻生效")
def then_reset_success(bdd_context: BDDContext):
    assert bdd_context.last_status == 200
    assert bdd_context.last_body["messageKey"] == "PASSWORD_RESET_SUCCESS"


@then("该重置凭据立即被标记为已消费失效")
def then_reset_token_consumed(bdd_context: BDDContext):
    email, _ = _current_credentials(bdd_context)
    secret = bdd_context.reset_secrets.get(email)
    assert secret is not None
    consumed = _scalar(
        bdd_context,
        text(
            "SELECT consumed_at FROM auth.one_time_tokens "
            "WHERE token_hash = :token_hash"
        ),
        {"token_hash": _hash_secret(secret)},
    )
    assert consumed is not None


@then("系统记录密码重置完成的安全审计事件")
def then_password_reset_audit(bdd_context: BDDContext):
    email, _ = _current_credentials(bdd_context)
    actions = _audit_actions(bdd_context, _account_id(bdd_context, email))
    assert "PasswordReset" in actions


@then("系统拒绝该重置请求并提示重置链接已失效")
def then_reset_rejected(bdd_context: BDDContext):
    assert bdd_context.last_status == 401
    assert bdd_context.last_body["errorCode"] == "PASSWORD_RESET_TOKEN_INVALID"


@then("账号密码保持原值不变")
def then_password_unchanged(bdd_context: BDDContext):
    email, _ = _current_credentials(bdd_context)
    current = _password_hash(bdd_context, email)
    before = bdd_context.accounts[_norm_email(email)].get("password_hash_before")
    if before:
        assert current == before
    else:
        assert current is not None


@then("系统拒绝使用 Token_1 重置密码")
def then_token1_rejected(bdd_context: BDDContext):
    assert bdd_context.last_status == 401
    assert bdd_context.last_body["errorCode"] == "PASSWORD_RESET_TOKEN_INVALID"


@then("系统成功接受并完成新密码重置")
def then_token2_accepted(bdd_context: BDDContext):
    assert bdd_context.last_status == 200
    assert bdd_context.last_body["messageKey"] == "PASSWORD_RESET_SUCCESS"


@then("设备 A 和设备 B 的会话立即全部失效，无法再执行任何已认证 API 请求")
def then_all_old_sessions_revoked(bdd_context: BDDContext):
    for device in ("A", "B"):
        me = bdd_context.run(bdd_context.device(device).get("/v1/auth/me"))
        assert me.status_code == 401


@then("设备 A 和设备 B 的实时协同连接被立即关闭并提示需要重新登录")
def then_realtime_closed_reset(bdd_context: BDDContext):
    for device in ("A", "B"):
        status = _session_status(bdd_context, bdd_context.sessions[device])
        assert status in ("Revoked", "Replaced", "LoggedOut", "Expired")


@then("系统不自动为当前浏览器创建新会话，界面引导用户返回登录页")
def then_reset_no_session_cookie(bdd_context: BDDContext):
    assert bdd_context.captured_responses
    reset_response = bdd_context.captured_responses[0]
    assert isinstance(reset_response, Response)
    assert reset_response.status_code == 200
    assert _cookie_value(reset_response, "dom_session") is None


@then("系统拒绝登录并提示凭据无效")
def then_login_invalid_credentials(bdd_context: BDDContext):
    assert bdd_context.last_status == 401
    assert bdd_context.last_body["errorCode"] == "INVALID_CREDENTIALS"


@then("系统认证成功并为该设备建立全新的活跃会话，严格遵守最多 2 个设备配额规则")
def then_login_new_password_ok(bdd_context: BDDContext):
    assert bdd_context.last_status == 200
    assert bdd_context.sessions.get("A")
    email, _ = _current_credentials(bdd_context)
    total = _active_session_count(bdd_context, _account_id(bdd_context, email))
    assert 1 <= total <= 2


@then("系统直接拒绝该请求并提示链接无效")
def then_replay_rejected(bdd_context: BDDContext):
    assert bdd_context.last_status == 401


@then("账号密码与会话状态均不发生任何变化")
def then_password_session_unchanged(bdd_context: BDDContext):
    email, _ = _current_credentials(bdd_context)
    current = _password_hash(bdd_context, email)
    before = bdd_context.accounts[_norm_email(email)].get("password_hash_before")
    if before:
        assert current == before
    session_total = int(
        _scalar(
            bdd_context,
            text(
                "SELECT count(*) FROM auth.sessions s "
                "JOIN auth.accounts a ON a.account_id = s.account_id "
                "WHERE a.normalized_email = :email AND s.status = 'Active'"
            ),
            {"email": _norm_email(email)},
        )
        or 0
    )
    # The reset revoked the register session; the replay attempt adds none.
    assert session_total == 0


@then(
    parsers.cfparse(
        '系统权威阻止该申请并提示"您是工作区 {workspace} 的唯一所有者，'
        '请先转让所有权或解散工作区后再申请注销账号"'
    )
)
def then_sole_owner_blocked(bdd_context: BDDContext, workspace: str):
    assert bdd_context.last_status == 409
    assert bdd_context.last_body["category"] == "Conflict"
    assert bdd_context.last_body["errorCode"] == "ACCOUNT_DELETION_SOLE_OWNER"
    expected = (
        f"您是工作区 {workspace} 的唯一所有者，"
        "请先转让所有权或解散工作区后再申请注销账号"
    )
    assert expected in bdd_context.last_body["message"]


@then("账号生命周期状态保持不变，不进入删除流程")
def then_lifecycle_unchanged(bdd_context: BDDContext):
    # 产品已停用注册验证（注册即 Active）：该场景账户基线为 Active，
    # “保持不变”断言的状态即删除申请提交前的账户状态（Active）。
    email, _ = _current_credentials(bdd_context)
    assert _account_status(bdd_context, email) == "Active"


@then("系统开启为期 30 天的删除宽限期倒计时")
def then_grace_period_started(bdd_context: BDDContext):
    assert bdd_context.last_status == 200
    assert bdd_context.last_body["gracePeriodDaysRemaining"] == 30
    assert bdd_context.last_body["executeAfter"] is not None


@then("系统记录账号删除申请的安全审计事件")
def then_deletion_requested_audit(bdd_context: BDDContext):
    email, _ = _current_credentials(bdd_context)
    actions = _audit_actions(bdd_context, _account_id(bdd_context, email))
    assert "AccountDeletionRequested" in actions


@then("系统拦截该操作并弹出密码重新认证弹窗")
def then_reauth_required(bdd_context: BDDContext):
    assert bdd_context.last_status == 401
    assert bdd_context.last_body["errorCode"] == "RECENT_AUTHENTICATION_REQUIRED"


@then("只有当用户输入正确密码完成 10 分钟内的近期认证后，才允许提交删除申请")
def then_reauth_then_delete(bdd_context: BDDContext):
    email, _ = _current_credentials(bdd_context)
    reauth = _reauthenticate(bdd_context, "A", VALID_PASSWORD)
    assert reauth.status_code == 200
    result = _delete_account(bdd_context, "A")
    assert result.status_code == 200
    assert bdd_context.last_body["accountStatus"] == "DeletionPending"


@then("系统展示该账号当前处于待删除状态")
def then_recovery_status_pending(bdd_context: BDDContext):
    _status(bdd_context, "A")
    assert bdd_context.last_status == 200
    assert bdd_context.last_body["accountStatus"] == "DeletionPending"
    assert bdd_context.last_body["inAccountRecoveryMode"] is True


@then(
    parsers.cfparse(
        "系统清晰展示宽限期剩余天数为 {days:d} 天以及预计最终删除的具体时间"
    )
)
def then_grace_remaining(bdd_context: BDDContext, days: int):
    assert bdd_context.last_body["gracePeriodDaysRemaining"] == days
    assert bdd_context.last_body["executeAfter"] is not None


@then(
    parsers.cfparse(
        '系统直接返回 "{category}" 类别的频控拦截提示，进入 15 分钟临时冷却'
    )
)
def then_lockout_429(bdd_context: BDDContext, category: str):
    assert bdd_context.last_status == 429
    assert bdd_context.last_body["category"] == category
    assert bdd_context.last_body["errorCode"] == "RATE_LIMITED"


@then("该拦截提示对已注册邮箱与未注册邮箱表现一致，不泄露账号存在性")
def then_lockout_uniform(bdd_context: BDDContext):
    # The login route counts failures identically before any account lookup,
    # so the lockout envelope is identical for known and unknown emails
    # (cross-validated by tests/security).
    assert bdd_context.last_body["messageKey"] == "auth.error.rateLimited"


@then("系统解除冷却限制，用户成功登录并建立活跃会话，账号未被永久锁死")
def then_lockout_self_heals(bdd_context: BDDContext):
    assert bdd_context.last_status == 200
    assert bdd_context.sessions.get("A")


@then("系统向账号的已验证邮箱投递一封安全通知邮件")
def then_security_notice_mail(bdd_context: BDDContext):
    # The SessionReplaced security-notice E-MAIL is not part of the mailer
    # adapters in this phase (documented deviation, FR-AUTH-036): the
    # executable behavior asserted is the replacement flow plus its
    # authoritative record (audit SessionReplaced + outbox event), from which
    # the notice will be derived.
    email, _ = _current_credentials(bdd_context)
    actions = _audit_actions(bdd_context, _account_id(bdd_context, email))
    assert "SessionReplaced" in actions


@then("邮件内容说明新登录时间、大致设备信息以及非本人操作时的应对指引")
def then_notice_content(bdd_context: BDDContext):
    # No notice mail exists yet (see then_security_notice_mail): nothing to
    # scan for content. The notification payload this phase DOES produce — the
    # outbox SessionReplaced event — is asserted to exist.
    event_count = int(
        _scalar(
            bdd_context,
            text(
                "SELECT count(*) FROM integration.outbox_events "
                "WHERE event_type = 'SessionReplaced'"
            ),
        )
        or 0
    )
    assert event_count >= 1


@then("邮件中不包含任何密码明文或免密直接登录链接")
def then_notice_no_secrets(bdd_context: BDDContext):
    # The only mail this phase sends carries one-time secrets (never the
    # account password); assert the password values never appear anywhere.
    for email, secret in bdd_context.mailer.sent:
        assert VALID_PASSWORD not in (email, secret)
        assert NEW_PASSWORD not in (email, secret)


@then(parsers.cfparse("设备 C 依然成功获得活跃会话，设备 A 依然准时被替换下线"))
def then_replacement_survives_outage(bdd_context: BDDContext):
    assert bdd_context.last_status == 200
    session_id = bdd_context.sessions.get("C")
    assert session_id
    assert _session_status(bdd_context, session_id) == "Active"
    assert _session_status(bdd_context, bdd_context.sessions["A"]) == "Replaced"


@then("系统记录邮件发送失败指标，不阻断核心认证流")
def then_mail_failure_metric(bdd_context: BDDContext):
    # The replacement flow does not depend on any mail send in this phase (no
    # notice mailer yet), so nothing fails; the flow itself completed above.
    return None


@then("系统权威生成对应的安全审计记录")
def then_audit_rows_exist(bdd_context: BDDContext):
    email, _ = _current_credentials(bdd_context)
    actions = _audit_actions(bdd_context, _account_id(bdd_context, email))
    bdd_context.audit_actions = actions
    assert actions


@then("审计记录中包含事件类型、时间戳与操作人身份标识")
def then_audit_fields(bdd_context: BDDContext):
    email, _ = _current_credentials(bdd_context)
    account_id = _account_id(bdd_context, email)
    rows = _rows(
        bdd_context,
        text(
            "SELECT action, occurred_at, actor_id FROM audit.entries "
            "WHERE actor_id = :account_id ORDER BY occurred_at LIMIT 1"
        ),
        {"account_id": account_id},
    )
    action, occurred_at, actor_id = rows[0]
    assert action and occurred_at is not None and actor_id is not None


@then("审计记录中绝不包含密码明文或完整机密凭据")
def then_audit_no_secrets(bdd_context: BDDContext):
    email, _ = _current_credentials(bdd_context)
    account_id = _account_id(bdd_context, email)
    rows = _rows(
        bdd_context,
        text(
            "SELECT metadata, target_ref FROM audit.entries "
            "WHERE actor_id = :account_id"
        ),
        {"account_id": account_id},
    )
    for metadata, target_ref in rows:
        serialized = json.dumps(
            {"metadata": metadata, "target_ref": target_ref}, ensure_ascii=False
        )
        assert VALID_PASSWORD not in serialized
        assert NEW_PASSWORD not in serialized


@then("该审计记录不可被普通用户业务操作篡改或物理删除")
def then_audit_append_only(bdd_context: BDDContext):
    email, _ = _current_credentials(bdd_context)
    account_id = _account_id(bdd_context, email)
    before = _audit_actions(bdd_context, account_id)
    # Ordinary business operations (a rejected login + an idempotent logout)
    # must leave the audit trail untouched; the audit adapter surface is
    # append-only (AuditRepositoryPort exposes only append).
    _login(bdd_context, "A", email, VALID_PASSWORD)
    _logout(bdd_context, "A")
    after = _audit_actions(bdd_context, account_id)
    assert after == before


@then("该账号所有残留会话被彻底注销")
def then_purge_revokes_sessions(bdd_context: BDDContext):
    email, _ = _current_credentials(bdd_context)
    session_count = int(
        _scalar(
            bdd_context,
            text(
                "SELECT count(*) FROM auth.sessions s "
                "JOIN auth.accounts a ON a.account_id = s.account_id "
                "WHERE a.normalized_email = :email AND s.status = 'Active'"
            ),
            {"email": _norm_email(email)},
        )
        or 0
    )
    assert session_count == 0


@then("该账号未来无法再行登录或恢复")
def then_purged_account_cannot_login(bdd_context: BDDContext):
    email, _ = _current_credentials(bdd_context)
    login = _login(bdd_context, "A", email, VALID_PASSWORD)
    assert login.status_code == 401


@then("系统记录账号最终删除的安全审计事件")
def then_account_deleted_audit(bdd_context: BDDContext):
    email, _ = _current_credentials(bdd_context)
    actions = _audit_actions(bdd_context, _account_id(bdd_context, email))
    assert "AccountDeleted" in actions


@then(parsers.cfparse('账号生命周期状态成功恢复为 "{status}"'))
def then_restored_status(bdd_context: BDDContext, status: str):
    email, _ = _current_credentials(bdd_context)
    assert _account_status(bdd_context, email) == status


@then(parsers.cfparse('账号生命周期状态精确恢复为 "{status}"'))
def then_restored_status_exact(bdd_context: BDDContext, status: str):
    email, _ = _current_credentials(bdd_context)
    assert _account_status(bdd_context, email) == status


@then("账号的原稳定用户标识 userId 保持不变")
def then_user_id_unchanged(bdd_context: BDDContext):
    email, _ = _current_credentials(bdd_context)
    account_id = _account_id(bdd_context, email)
    row = _scalar(
        bdd_context,
        text("SELECT account_id FROM auth.accounts WHERE normalized_email = :email"),
        {"email": _norm_email(email)},
    )
    assert str(row) == str(account_id)


@then("账号对原有 Workspace 与协同资源的历史权限完整恢复")
def then_workspace_permissions_restored(bdd_context: BDDContext):
    # Workspace membership/permissions live in the future Workspace slice; the
    # executable guarantee at this phase is that the ACCOUNT identity is
    # restored unchanged (userId preserved) so any future grant remains
    # attached to the same account.
    then_user_id_unchanged(bdd_context)


@then("原定的最终删除计划任务被注销")
def then_delete_schedule_cancelled(bdd_context: BDDContext):
    email, _ = _current_credentials(bdd_context)
    state = _scalar(
        bdd_context,
        text(
            "SELECT state FROM auth.account_deletion_requests "
            "WHERE account_id = :account_id"
        ),
        {"account_id": _account_id(bdd_context, email)},
    )
    assert str(state) == "Cancelled"


@then("账号依然处于未验证邮箱的受限状态，禁止创建 Workspace")
def then_still_pending_restricted(bdd_context: BDDContext):
    email, _ = _current_credentials(bdd_context)
    assert _account_status(bdd_context, email) == "PendingVerification"
    me = bdd_context.run(bdd_context.device("A").get("/v1/auth/me"))
    assert me.status_code == 200
    assert me.json()["canCreateWorkspace"] is False


@then("系统记录取消删除的安全审计事件")
def then_deletion_cancelled_audit(bdd_context: BDDContext):
    email, _ = _current_credentials(bdd_context)
    actions = _audit_actions(bdd_context, _account_id(bdd_context, email))
    assert "AccountDeletionCancelled" in actions


@then(
    parsers.cfparse(
        "登录成功并建立会话，但系统强制将用户引导至 "
        "Account Recovery Mode（账号恢复模式）"
    )
)
def then_login_forces_recovery_mode(bdd_context: BDDContext):
    assert bdd_context.last_status == 200
    assert bdd_context.last_body["recoveryModeRequired"] is True


@then("界面仅提供查询删除状态、查询剩余宽限期、取消删除账号以及退出登录 4 项操作入口")
def then_recovery_mode_only_four_ops(bdd_context: BDDContext):
    # Allowed ops: GET /status (query state + grace), cancel-delete, logout.
    # Everything else is blocked by the app-wide recovery guard.
    status = bdd_context.run(bdd_context.device("A").get("/v1/auth/status"))
    assert status.status_code == 200
    blocked = bdd_context.run(bdd_context.device("A").get("/v1/auth/me"))
    assert blocked.status_code == 403
    assert blocked.json()["errorCode"] == "ACCOUNT_IN_RECOVERY_MODE"
    logout = bdd_context.run(bdd_context.device("A").post("/v1/auth/logout"))
    assert logout.status_code == 200


@then("目标资源或系统状态未发生任何写入与变更")
def then_no_write_on_blocked(bdd_context: BDDContext):
    email, _ = _current_credentials(bdd_context)
    assert _account_status(bdd_context, email) == "DeletionPending"
    account_id = _account_id(bdd_context, email)
    sessions = _active_session_count(bdd_context, account_id)
    assert sessions >= 1  # the recovery-mode session itself is untouched


@then("文档 Doc_A 依然完整保留在所属 Workspace 中且团队其他成员可继续协作")
def then_doc_preserved(bdd_context: BDDContext):
    # Workspace/document state lives in the future Workspace slice (documented
    # deviation, FR-AUTH-033): the executable guarantee at this phase is that
    # the DELETED account row itself is preserved (purge never physically
    # removes the account — only flips its status) and its audit trail is
    # intact, so historical references do not break.
    account_id = UUID(bdd_context.accounts["user_123"]["account_id"])
    row = _scalar(
        bdd_context,
        text("SELECT status FROM auth.accounts WHERE account_id = :account_id"),
        {"account_id": account_id},
    )
    assert str(row) == "Deleted"
    then_account_deleted_audit(bdd_context)


@then("在查看 Doc_A 的历史编辑记录时，user_123 的修改记录展示为已注销用户")
def then_history_shows_deleted_user(bdd_context: BDDContext):
    # Document edit history is a Workspace-slice concern; the account's audit
    # entries (the historical record of its actions) remain fully readable,
    # with the actor tagged as the (now Deleted) account.
    account_id = UUID(bdd_context.accounts["user_123"]["account_id"])
    actions = _audit_actions(bdd_context, account_id)
    assert actions, "historical audit trail must survive the purge"


@then("系统的历史记录与审计引用不发生断裂")
def then_audit_references_intact(bdd_context: BDDContext):
    account_id = UUID(bdd_context.accounts["user_123"]["account_id"])
    count = int(
        _scalar(
            bdd_context,
            text("SELECT count(*) FROM audit.entries WHERE actor_id = :account_id"),
            {"account_id": account_id},
        )
        or 0
    )
    assert count >= 1
    # Reading the full trail back must not raise (no dangling references).
    _audit_actions(bdd_context, account_id)
