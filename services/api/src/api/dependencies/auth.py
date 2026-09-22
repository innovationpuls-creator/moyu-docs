"""Shared dependencies for auth routes (plan Task 21 §1).

- ``get_db_session``: override-friendly Postgres session (app_infra engine).
- ``get_valkey`` / ``get_rate_limiter``: Valkey client + auth RateLimiter.
- ``get_device_id``: stable per-browser ``dom_device`` cookie, set if absent.
- Cookie helpers for ``dom_session`` / ``dom_device`` (HttpOnly, SameSite=Lax,
  Secure outside debug — doc 16 §30-§33/§97).
- External success message keys, sourced from UNIFORM_AUTH_MESSAGES names so
  the anti-enumeration copy stays single-sourced (doc 27 §17 / FR-AUTH-007).
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

from app_core.account.domain.timing_shield import UNIFORM_AUTH_MESSAGES
from app_core.session.domain.session import Session
from app_infra.postgres.engine import get_db_session as engine_get_db_session
from app_infra.valkey.rate_limiter import (
    RESEND_COOLDOWN_SECONDS,
    RateLimiter,
)
from fastapi import Request, Response
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from api.config import settings
from api.mailer import LoggingMailer

SESSION_COOKIE = settings.session_cookie
DEVICE_COOKIE = settings.device_cookie

# Anti-enumeration success keys (FR-AUTH-005/007): the messageKeys ARE the
# UNIFORM_AUTH_MESSAGES names so the external payload never encodes whether an
# email exists. Generated DTOs carry only the stable messageKey; the human
# copy stays in UNIFORM_AUTH_MESSAGES (server-side, single source) until the
# client-localization layer lands.
REGISTER_SUCCESS_KEY = "REGISTER_SUCCESS"
FORGOT_PASSWORD_SUCCESS_KEY = "FORGOT_PASSWORD_SUCCESS"
EMAIL_VERIFIED_KEY = "EMAIL_VERIFIED"
VERIFICATION_EMAIL_RESENT_KEY = "VERIFICATION_EMAIL_RESENT"

# Drift guard: the messageKey constants above must stay aligned with the
# canonical UNIFORM_AUTH_MESSAGES names (single source, FR-AUTH-007).
assert {"REGISTER_SUCCESS", "FORGOT_PASSWORD_SUCCESS"} <= set(UNIFORM_AUTH_MESSAGES)


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


async def get_db_session() -> AsyncIterator[AsyncSession]:
    async with engine_get_db_session() as session:
        yield session


def get_mailer() -> LoggingMailer:
    """Dev mailer adapter (log-delivered); tests override this dependency."""
    return LoggingMailer()


async def get_valkey(request: Request) -> Redis:
    valkey = getattr(request.app.state, "valkey", None)
    if valkey is None:
        valkey = Redis.from_url(settings.valkey_url, decode_responses=True)
        request.app.state.valkey = valkey
    return valkey


async def get_rate_limiter(request: Request) -> RateLimiter:
    client = await get_valkey(request)
    return RateLimiter(client)


def _cookie_secure() -> bool:
    return not settings.debug


def set_device_cookie(response: Response, device_id: str) -> None:
    response.set_cookie(
        key=DEVICE_COOKIE,
        value=device_id,
        max_age=settings.device_cookie_max_age,
        httponly=True,
        secure=_cookie_secure(),
        samesite="lax",
        path="/",
    )


def get_device_id(request: Request, response: Response) -> str:
    """Resolve the stable browser device id (FR-AUTH-013); issued on first
    request and persisted in the HttpOnly ``dom_device`` cookie."""
    device_id = request.cookies.get(DEVICE_COOKIE)
    if not device_id:
        device_id = uuid4().hex
        set_device_cookie(response, device_id)
    return device_id


def set_session_cookie(response: Response, session: Session) -> None:
    response.set_cookie(
        key=SESSION_COOKIE,
        value=str(session.session_id),
        httponly=True,
        secure=_cookie_secure(),
        samesite="lax",
        path="/",
        expires=session.expires_at,
    )


def clear_session_cookie(response: Response) -> None:
    response.delete_cookie(
        SESSION_COOKIE,
        path="/",
        httponly=True,
        secure=_cookie_secure(),
        samesite="lax",
    )


def resend_quota_key(email: str) -> UUID:
    """Deterministic rate-limit identity for an UNREGISTERED email so the
    resend endpoint behaves identically for known and unknown addresses
    (anti-enumeration, FR-AUTH-007). Registered accounts key on account_id."""
    return uuid.uuid5(uuid.NAMESPACE_URL, f"dom:resend-verification:{email.casefold()}")


def resend_next_allowed_at(now: datetime) -> datetime:
    return now + timedelta(seconds=RESEND_COOLDOWN_SECONDS)
