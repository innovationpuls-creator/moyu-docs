from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timezone

from app_core.account.application.registration import (
    RegisterAccount,
    VerificationMailer,
)
from app_core.session.application.authentication import LoginWithPassword
from sqlalchemy.ext.asyncio import AsyncSession

from app_infra.postgres.account_repository import PostgresAccountRepository
from app_infra.postgres.audit_repository import PostgresAuditRepository
from app_infra.postgres.idempotency_repository import PostgresIdempotencyRepository
from app_infra.postgres.session_repository import PostgresSessionRepository
from app_infra.postgres.token_repository import PostgresTokenRepository


def build_registration_use_case(
    session: AsyncSession,
    mailer: VerificationMailer,
    *,
    now: Callable[[], datetime],
) -> RegisterAccount:
    return RegisterAccount(
        PostgresAccountRepository(session),
        PostgresSessionRepository(session),
        PostgresTokenRepository(session),
        PostgresAuditRepository(session),
        mailer,
        idempotency=PostgresIdempotencyRepository(session),
        now=now,
    )


def build_login_use_case(
    session: AsyncSession,
    *,
    now: Callable[[], datetime] | None = None,
) -> LoginWithPassword:
    return LoginWithPassword(
        PostgresAccountRepository(session),
        PostgresSessionRepository(session),
        idempotency=PostgresIdempotencyRepository(session),
        now=now or (lambda: datetime.now(timezone.utc)),
    )
