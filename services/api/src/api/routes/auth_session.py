"""Auth session routes (plan Task 22): login / logout / me / session.

Boundary discipline (doc 27 §16/§17, doc 28 §48): request/response bodies are
the GENERATED app-contracts DTOs; use-case results (LoginResult) are mapped to
them at the boundary. No domain SQL lives here.

- POST /v1/auth/login: LoginWithPassword -> full credential check via
  build_login_use_case; composite rate-limit identity (IP + device id) with a
  15-minute temporary lockout after 5 failures (FR-AUTH-035); success ALWAYS
  rotates the session credential (FR-AUTH-008); the new session is cached and
  replaced sessions trigger a Valkey invalidation event (FR-AUTH-015).
- POST /v1/auth/logout: no-body command (registry requestBody: none) — the
  session id comes from the dom_session cookie; idempotent (Bad logging out an
  already-invalid session succeeds with AlreadyLoggedOut, FR-AUTH-020 AC-020.4).
- GET /v1/auth/me + GET /v1/auth/session: account / current-session queries
  (FR-AUTH-022) guarded by get_current_session.
"""

from __future__ import annotations

from uuid import UUID

from app_contracts.commands.auth.login_with_password import (
    LoginWithPassword,
    LoginWithPasswordResponse,
    SessionSummary,
)
from app_contracts.commands.auth.logout import (
    LogoutResponse,
    LogoutStatusValue,
)
from app_contracts.ids import ids
from app_contracts.queries.auth.get_current_account import GetCurrentAccountResponse
from app_contracts.queries.auth.get_current_session import GetCurrentSessionResponse
from app_core.account.domain.timing_shield import UNIFORM_AUTH_MESSAGES
from app_core.common.exceptions import AuthenticationError
from app_core.session.application.authentication import Logout as LogoutUseCase
from app_core.session.domain.session import Session, SessionInvalidationReason
from app_core.session.ports.session_cache import SessionCachePort
from app_infra.postgres.account_repository import PostgresAccountRepository
from app_infra.postgres.registration_composition import build_login_use_case
from app_infra.postgres.session_repository import PostgresSessionRepository
from app_infra.valkey.rate_limiter import RateLimiter
from fastapi import APIRouter, Depends, Header, Request, Response
from sqlalchemy.ext.asyncio import AsyncSession

from api.dependencies.auth import (
    LOGOUT_SUCCESS_KEY,
    clear_session_cookie,
    get_current_session,
    get_db_session,
    get_device_id,
    get_rate_limiter,
    get_session_cache,
    set_session_cookie,
    utc_now,
)

router = APIRouter()


def _login_rate_identifier(request: Request, device_id: str) -> str:
    """Composite rate-limit identity (IP + device id, doc 16 §54 / FR-AUTH-035).
    Absent client context falls back to 'unknown' so the limiter key stays
    deterministic per device."""
    client = request.client
    host = client.host if client is not None else "unknown"
    return f"{host}:{device_id}"


@router.post("/login", response_model=LoginWithPasswordResponse)
async def login(
    body: LoginWithPassword,
    request: Request,
    response: Response,
    session: AsyncSession = Depends(get_db_session),
    device_id: str = Depends(get_device_id),
    rate_limiter: RateLimiter = Depends(get_rate_limiter),
    cache: SessionCachePort = Depends(get_session_cache),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> LoginWithPasswordResponse:
    identifier = _login_rate_identifier(request, device_id)
    await rate_limiter.check_login_rate(identifier)
    use_case = build_login_use_case(session, now=utc_now)
    try:
        result = await use_case.execute(
            body.email, body.password, device_id, idempotency_key=idempotency_key
        )
    except AuthenticationError:
        # Both wrong-password and unknown-email land here with the identical
        # INVALID_CREDENTIALS error (FR-AUTH-007); count them toward the
        # lockout, then re-raise for the error envelope.
        await rate_limiter.record_login_failure(identifier)
        raise
    await rate_limiter.clear_login_failure(identifier)

    # Rotation (FR-AUTH-008): always hand out the NEWLY created session id.
    set_session_cookie(response, result.session)
    # Cache the new session so the fast path works; publish invalidation for
    # every replaced session (FR-AUTH-015 5s cross-instance convergence).
    await cache.set_session(result.session)
    for replaced in result.replaced_sessions:
        await cache.publish_invalidation(
            replaced.session_id, SessionInvalidationReason.NEW_DEVICE_LOGIN.value
        )

    return LoginWithPasswordResponse(
        accountId=result.account.account_id,
        accountStatus=ids.AccountStatusValue(result.account.status.value),
        session=_session_summary(result.session, current_device=True),
        recoveryModeRequired=result.recovery_mode,
    )


@router.post("/logout", response_model=LogoutResponse)
async def logout(
    request: Request,
    response: Response,
    session: AsyncSession = Depends(get_db_session),
    cache: SessionCachePort = Depends(get_session_cache),
) -> LogoutResponse:
    session_id = _session_id_from_cookie(request)
    if session_id is None:
        return _logout_response(response, LogoutStatusValue.AlreadyLoggedOut)
    sessions = PostgresSessionRepository(session)
    record = await sessions.find_by_id(session_id)
    if record is None or not record.is_active(utc_now()):
        return _logout_response(response, LogoutStatusValue.AlreadyLoggedOut)
    await LogoutUseCase(sessions).execute(session_id)
    await cache.invalidate_session(session_id)
    return _logout_response(response, LogoutStatusValue.LoggedOut)


@router.get("/me", response_model=GetCurrentAccountResponse)
async def me(
    current: Session = Depends(get_current_session),
    session: AsyncSession = Depends(get_db_session),
) -> GetCurrentAccountResponse:
    account_record = await PostgresAccountRepository(session).find_by_account_id(
        current.account_id
    )
    if account_record is None:
        raise AuthenticationError(
            UNIFORM_AUTH_MESSAGES["INVALID_CREDENTIALS_EN"], "INVALID_CREDENTIALS"
        )
    account = account_record.account
    return GetCurrentAccountResponse(
        accountId=account.account_id,
        primaryEmail=account.primary_email,
        accountStatus=ids.AccountStatusValue(account.status.value),
        emailVerifiedAt=account.email_verified_at,
        createdAt=account.created_at,
        canCreateWorkspace=account.can_create_workspace(),
        inAccountRecoveryMode=account.is_in_recovery_mode(),
    )


@router.get("/session", response_model=GetCurrentSessionResponse)
async def current_session(
    current: Session = Depends(get_current_session),
    device_id: str = Depends(get_device_id),
) -> GetCurrentSessionResponse:
    return _current_session_response(
        current, current_device=current.device_id == device_id
    )


def _current_session_response(
    session: Session, *, current_device: bool
) -> GetCurrentSessionResponse:
    return GetCurrentSessionResponse(
        sessionId=session.session_id,
        createdAt=session.created_at,
        lastSeenAt=session.last_seen_at,
        expiresAt=session.expires_at,
        currentDevice=current_device,
        status=ids.SessionStatusValue(session.status.value),
        lastStrongAuthAt=session.last_strong_auth_at,
    )


def _session_summary(session: Session, *, current_device: bool) -> SessionSummary:
    return SessionSummary(
        sessionId=session.session_id,
        createdAt=session.created_at,
        lastSeenAt=session.last_seen_at,
        expiresAt=session.expires_at,
        currentDevice=current_device,
        status=ids.SessionStatusValue(session.status.value),
        lastStrongAuthAt=session.last_strong_auth_at,
    )


def _session_id_from_cookie(request: Request) -> UUID | None:
    raw = request.cookies.get("dom_session")
    if not raw:
        return None
    try:
        return UUID(raw)
    except ValueError:
        return None


def _logout_response(
    response: Response,
    status: LogoutStatusValue,
) -> LogoutResponse:
    clear_session_cookie(response)
    return LogoutResponse(messageKey=LOGOUT_SUCCESS_KEY, sessionStatus=status)
