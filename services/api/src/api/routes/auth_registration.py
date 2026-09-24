"""Auth registration routes (plan Task 21 §2): register / verify-email /
resend-verification.

Boundary discipline (doc 27 §16/§17, doc 28 §48): the request/response bodies
are the GENERATED app-contracts DTOs; use-case results (RegistrationResult,
Account) are mapped to them at the boundary. No domain SQL lives here.

Anti-enumeration (FR-AUTH-005/007) after the USER RULING (2026-09-23): register
returns 201 for BOTH new and existing emails with an IDENTICAL body; a session
cookie is issued ONLY for a newly created account. The residual email-existence
oracle via Set-Cookie absence is an ACCEPTED product risk, mitigated by (a) the
register rate limiter below and (b) the TimingShield latency equalization —
both mitigations are MANDATORY. Resend-verification returns the same payload
whether or not the email is registered (Valkey quota keyed on account_id for
known accounts, deterministic email-derived id otherwise).
"""

from __future__ import annotations

import hashlib

from app_contracts.commands.auth.register_with_email import (
    RegisterWithEmail,
    RegisterWithEmailResponse,
)
from app_contracts.commands.auth.resend_email_verification import (
    ResendEmailVerification,
    ResendEmailVerificationResponse,
)
from app_contracts.commands.auth.verify_email import (
    VerifyEmail,
    VerifyEmailResponse,
)
from app_contracts.ids import ids
from app_core.account.application.registration import (
    ResendVerificationEmail,
    VerificationMailer,
)
from app_core.account.application.registration import (
    VerifyEmail as VerifyEmailUseCase,
)
from app_core.account.domain.account import AccountStatus
from app_core.account.domain.token import OneTimeTokenType
from app_core.common.exceptions import AuthenticationError
from app_infra.postgres.account_repository import PostgresAccountRepository
from app_infra.postgres.audit_repository import PostgresAuditRepository
from app_infra.postgres.registration_composition import (
    build_registration_use_case,
)
from app_infra.postgres.token_repository import PostgresTokenRepository
from app_infra.valkey.rate_limiter import RateLimiter
from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy.ext.asyncio import AsyncSession

from api.dependencies.auth import (
    EMAIL_VERIFIED_KEY,
    REGISTER_SUCCESS_KEY,
    VERIFICATION_EMAIL_RESENT_KEY,
    composite_rate_identifier,
    get_db_session,
    get_device_id,
    get_mailer,
    get_rate_limiter,
    resend_next_allowed_at,
    resend_quota_key,
    set_session_cookie,
    utc_now,
)

router = APIRouter()


def _hash_token_secret(secret: str) -> str:
    """Canonical one-time-token hash (mirrors app_core.account.domain.token)."""
    return hashlib.sha256(secret.encode("utf-8")).hexdigest()


@router.post("/register", status_code=201, response_model=RegisterWithEmailResponse)
async def register(
    body: RegisterWithEmail,
    request: Request,
    response: Response,
    session: AsyncSession = Depends(get_db_session),
    device_id: str = Depends(get_device_id),
    mailer: VerificationMailer = Depends(get_mailer),
    rate_limiter: RateLimiter = Depends(get_rate_limiter),
) -> RegisterWithEmailResponse:
    # Register rate limiting (USER RULING mitigation (a), MANDATORY): checked
    # BEFORE the credential/email branch so known and unknown emails are
    # throttled identically (PRD §534 / FR-AUTH-004/035 spirit). Every valid
    # request counts toward the per-IP+device 5-per-15-minute window.
    identifier = composite_rate_identifier(request, device_id)
    await rate_limiter.check_register_rate(identifier)
    # 产品决策（2026-09）：停用邮箱验证，注册即 Active（require_verification=False）。
    # VerifyEmail/ResendVerificationEmail 端点保留为兼容层，不再有常规触发路径。
    use_case = build_registration_use_case(
        session, mailer, now=utc_now, require_verification=False
    )
    result = await use_case.execute(body.email, body.password, device_id)
    await rate_limiter.record_register_attempt(identifier)
    # 201 for BOTH new and existing emails (USER RULING): the HTTP status and
    # body are identical; the dom_session cookie is issued ONLY for a newly
    # created account (result.session is None exactly when the email already
    # existed — that path NEVER mints a session, FR-AUTH-005 / task-1 fix).
    if result.session is not None:
        set_session_cookie(response, result.session)
    return RegisterWithEmailResponse(
        messageKey=REGISTER_SUCCESS_KEY,
        email=result.account.primary_email,
    )


@router.post("/verify-email", response_model=VerifyEmailResponse)
async def verify_email(
    body: VerifyEmail,
    session: AsyncSession = Depends(get_db_session),
) -> VerifyEmailResponse:
    # Resolve the owning account from the opaque secret WITHOUT consuming it;
    # VerifyEmailUseCase performs the authoritative consume + account checks.
    tokens = PostgresTokenRepository(session)
    token = await tokens.find_by_hash(_hash_token_secret(body.token))
    if token is None or token.token_type is not OneTimeTokenType.EMAIL_VERIFICATION:
        raise AuthenticationError(
            "EMAIL_VERIFICATION_TOKEN_INVALID", "EMAIL_VERIFICATION_TOKEN_INVALID"
        )
    use_case = VerifyEmailUseCase(
        PostgresAccountRepository(session),
        tokens,
        PostgresAuditRepository(session),
        now=utc_now,
    )
    account = await use_case.execute(body.token, token.account_id)
    return VerifyEmailResponse(
        messageKey=EMAIL_VERIFIED_KEY,
        accountStatus=ids.AccountStatusValue(account.status.value),
    )


@router.post("/resend-verification", response_model=ResendEmailVerificationResponse)
async def resend_verification(
    body: ResendEmailVerification,
    session: AsyncSession = Depends(get_db_session),
    rate_limiter: RateLimiter = Depends(get_rate_limiter),
    mailer: VerificationMailer = Depends(get_mailer),
) -> ResendEmailVerificationResponse:
    accounts = PostgresAccountRepository(session)
    record = await accounts.find_by_email(body.email)
    quota_key = (
        record.account.account_id
        if record is not None
        else resend_quota_key(body.email)
    )
    # Rate limit BEFORE branching so the 429 behavior cannot distinguish
    # registered from unregistered emails (FR-AUTH-004 / FR-AUTH-007).
    await rate_limiter.check_resend_verification_quota(quota_key)
    now = utc_now()
    if (
        record is not None
        and record.account.status is AccountStatus.PENDING_VERIFICATION
    ):
        use_case = ResendVerificationEmail(
            accounts,
            PostgresTokenRepository(session),
            mailer,
            now=utc_now,
            audit=PostgresAuditRepository(session),
        )
        await use_case.execute(record.account.account_id)
    await rate_limiter.record_resend_verification(quota_key)
    return ResendEmailVerificationResponse(
        messageKey=VERIFICATION_EMAIL_RESENT_KEY,
        nextAllowedAt=resend_next_allowed_at(now),
    )
