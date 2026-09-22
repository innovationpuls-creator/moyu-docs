"""Auth password routes (plan Task 23): forgot-password / reset-password /
reauthenticate.

Boundary discipline (doc 27 §16/§17, doc 28 §48): request/response bodies are
the GENERATED app-contracts DTOs; use-case results are mapped at the boundary.

- POST /v1/auth/forgot-password: uniform FORGOT_PASSWORD_SUCCESS body for
  registered AND unregistered emails (FR-AUTH-007/024; the missing-email path
  runs the TimingShield inside the use case). Rate-limited with the same
  cooldown/24h quota machinery as resend-verification (keyed on account_id for
  known emails / deterministic email-derived key otherwise, AC-024.3).
- POST /v1/auth/reset-password: PASSWORD_RESET_TOKEN_INVALID -> 401; success
  revokes ALL old sessions and changes the password hash (FR-AUTH-025/026/027);
  never sets a session cookie (user returns to login).
- POST /v1/auth/reauthenticate: recent-auth window establishment
  (FR-AUTH-034); INVALID_CREDENTIALS -> 401.
"""

from __future__ import annotations

from app_contracts.commands.auth.reauthenticate import (
    Reauthenticate,
    ReauthenticateResponse,
)
from app_contracts.commands.auth.request_password_reset import (
    RequestPasswordReset,
    RequestPasswordResetResponse,
)
from app_contracts.commands.auth.reset_password import (
    ResetPassword,
    ResetPasswordResponse,
)
from app_contracts.ids import ids
from app_core.account.application.password_reset import (
    PasswordResetMailer,
)
from app_core.account.application.password_reset import (
    RequestPasswordReset as RequestPasswordResetUseCase,
)
from app_core.account.application.password_reset import (
    ResetPassword as ResetPasswordUseCase,
)
from app_core.common.exceptions import AuthenticationError
from app_core.session.application.authentication import (
    Reauthenticate as ReauthenticateUseCase,
)
from app_core.session.domain.session import Session, SessionPolicy
from app_infra.postgres.account_repository import PostgresAccountRepository
from app_infra.postgres.audit_repository import PostgresAuditRepository
from app_infra.postgres.session_repository import PostgresSessionRepository
from app_infra.postgres.token_repository import PostgresTokenRepository
from app_infra.valkey.rate_limiter import RateLimiter
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from api.dependencies.auth import (
    FORGOT_PASSWORD_SUCCESS_KEY,
    PASSWORD_RESET_SUCCESS_KEY,
    REAUTHENTICATED_KEY,
    get_current_session,
    get_db_session,
    get_mailer,
    get_rate_limiter,
    resend_next_allowed_at,
    resend_quota_key,
    utc_now,
)

router = APIRouter()


def _hash_token_secret(secret: str) -> str:
    """Canonical one-time-token hash (mirrors app_core.account.domain.token)."""
    import hashlib

    return hashlib.sha256(secret.encode("utf-8")).hexdigest()


@router.post("/forgot-password", response_model=RequestPasswordResetResponse)
async def forgot_password(
    body: RequestPasswordReset,
    session: AsyncSession = Depends(get_db_session),
    mailer: PasswordResetMailer = Depends(get_mailer),
    rate_limiter: RateLimiter = Depends(get_rate_limiter),
) -> RequestPasswordResetResponse:
    accounts = PostgresAccountRepository(session)
    record = await accounts.find_by_email(body.email)
    # Rate-limit BEFORE branching; known accounts key on account_id, unknown
    # emails on a deterministic email-derived key so the 429 behavior cannot
    # distinguish registered from unregistered addresses (FR-AUTH-007).
    quota_key = (
        record.account.account_id
        if record is not None
        else resend_quota_key(body.email)
    )
    await rate_limiter.check_resend_verification_quota(quota_key)
    now = utc_now()
    use_case = RequestPasswordResetUseCase(
        accounts,
        PostgresTokenRepository(session),
        PostgresAuditRepository(session),
        mailer,
        now=utc_now,
    )
    await use_case.execute(body.email)
    await rate_limiter.record_resend_verification(quota_key)
    return RequestPasswordResetResponse(
        messageKey=FORGOT_PASSWORD_SUCCESS_KEY,
        nextAllowedAt=resend_next_allowed_at(now),
    )


@router.post("/reset-password", response_model=ResetPasswordResponse)
async def reset_password(
    body: ResetPassword,
    session: AsyncSession = Depends(get_db_session),
) -> ResetPasswordResponse:
    accounts = PostgresAccountRepository(session)
    tokens = PostgresTokenRepository(session)
    # Resolve the owning account for the response DTO WITHOUT consuming the
    # secret; the use case performs the authoritative consume + validation.
    token = await tokens.find_by_hash(_hash_token_secret(body.token))
    if token is None:
        raise AuthenticationError(
            "PASSWORD_RESET_TOKEN_INVALID", "PASSWORD_RESET_TOKEN_INVALID"
        )
    use_case = ResetPasswordUseCase(
        accounts,
        tokens,
        PostgresSessionRepository(session),
        PostgresAuditRepository(session),
        now=utc_now,
    )
    await use_case.execute(body.token, body.newPassword)
    record = await accounts.find_by_account_id(token.account_id)
    if record is None:
        raise AuthenticationError(
            "PASSWORD_RESET_TOKEN_INVALID", "PASSWORD_RESET_TOKEN_INVALID"
        )
    return ResetPasswordResponse(
        messageKey=PASSWORD_RESET_SUCCESS_KEY,
        accountStatus=ids.AccountStatusValue(record.account.status.value),
    )


@router.post("/reauthenticate", response_model=ReauthenticateResponse)
async def reauthenticate(
    body: Reauthenticate,
    current: Session = Depends(get_current_session),
    session: AsyncSession = Depends(get_db_session),
) -> ReauthenticateResponse:
    use_case = ReauthenticateUseCase(
        PostgresAccountRepository(session),
        PostgresSessionRepository(session),
        now=utc_now,
    )
    updated = await use_case.execute(current.session_id, body.password)
    valid_until = updated.last_strong_auth_at + SessionPolicy.REAUTHENTICATION_WINDOW
    return ReauthenticateResponse(
        messageKey=REAUTHENTICATED_KEY,
        reauthenticatedAt=updated.last_strong_auth_at,
        validUntil=valid_until,
        windowSeconds=int(SessionPolicy.REAUTHENTICATION_WINDOW.total_seconds()),
    )
