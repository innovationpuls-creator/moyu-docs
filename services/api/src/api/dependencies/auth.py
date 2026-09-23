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
from app_core.common.exceptions import AuthenticationError
from app_core.session.domain.session import Session, SessionStatus
from app_core.session.ports.session_cache import (
    SessionCachedData,
    SessionCachePort,
)
from app_infra.postgres.engine import get_db_session as engine_get_db_session
from app_infra.postgres.session_repository import PostgresSessionRepository
from app_infra.valkey.rate_limiter import (
    RESEND_COOLDOWN_SECONDS,
    RateLimiter,
)
from app_infra.valkey.session_cache import ValkeySessionCache
from fastapi import Depends, Request, Response
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
# Non-anti-enumeration success keys (single-source messageKey for the generated
# response DTOs of the session / password / deletion command routes). These are
# API-layer keys, not anti-enumeration copy, so they are NOT part of
# UNIFORM_AUTH_MESSAGES.
LOGOUT_SUCCESS_KEY = "LOGOUT_SUCCESS"
PASSWORD_RESET_SUCCESS_KEY = "PASSWORD_RESET_SUCCESS"
REAUTHENTICATED_KEY = "REAUTHENTICATED"
DELETION_REQUESTED_KEY = "DELETION_REQUESTED"
DELETION_CANCELLED_KEY = "DELETION_CANCELLED"

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


def composite_rate_identifier(request: Request, device_id: str) -> str:
    """Composite rate-limit identity (IP + device id, doc 16 §54 / FR-AUTH-035).
    Absent client context falls back to 'unknown' so the limiter key stays
    deterministic per device (used by the login and register limiters)."""
    client = request.client
    host = client.host if client is not None else "unknown"
    return f"{host}:{device_id}"


def deletion_idempotency_key(account_id: UUID, header_key: str) -> str:
    """Account-scoped idempotency key for POST /v1/auth/delete-account
    (registry idempotencyRequirement: required). The Idempotency-Key header
    value is client-chosen, so it must never collide across accounts."""
    return f"delete-account:{account_id}:{header_key}"


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


# ---------------------------------------------------------------------------
# Current-session resolution (plan Task 22 §2)
# ---------------------------------------------------------------------------
#
# get_current_session is the shared authenticated-actor dependency for the
# protected auth routes. Fast path: Valkey session cache (5s TTL) rejects a
# REPLACED / EXPIRED snapshot without a Postgres round-trip (FR-AUTH-015 <=5s
# convergence; doc 16 §80, §125-126). PostgreSQL stays the authority (doc 16
# §79): on cache miss OR cache-actively-valid the authoritative row is loaded
# and re-validated with is_active(now) — the cache is disposable, never the
# source of truth (doc 16 §125).


def _invalid_session_error() -> AuthenticationError:
    # Registry has SESSION_EXPIRED / SESSION_REPLACED but no plain
    # "session not found" code; missing/invalid sessions reuse the registered
    # INVALID_CREDENTIALS (reported for Phase 9 registry alignment).
    return AuthenticationError(
        UNIFORM_AUTH_MESSAGES["INVALID_CREDENTIALS_EN"], "INVALID_CREDENTIALS"
    )


def _rejected_cache_state(
    cached: SessionCachedData, now: datetime
) -> AuthenticationError | None:
    """Map a cache snapshot that cannot authenticate (REPLACED / EXPIRED /
    logged-out / revoked) to its stable error, or None if the snapshot is a
    plausible active session (authoritative Postgres check still follows)."""
    if cached.status is SessionStatus.REPLACED:
        return AuthenticationError(
            "The session has been replaced by another device.", "SESSION_REPLACED"
        )
    if cached.status is SessionStatus.EXPIRED or cached.expires_at <= now:
        return AuthenticationError("The session has expired.", "SESSION_EXPIRED")
    if cached.status is not SessionStatus.ACTIVE:
        return _invalid_session_error()
    return None


def _rejected_db_state(session: Session, now: datetime) -> AuthenticationError | None:
    """Authoritative Postgres mapping: a replaced session is surfaced
    distinctly from an expired one (FR-AUTH-015 vs FR-AUTH-009)."""
    if session.status is SessionStatus.REPLACED:
        return AuthenticationError(
            "The session has been replaced by another device.", "SESSION_REPLACED"
        )
    session.expire_if_needed(now)
    if session.status is SessionStatus.EXPIRED:
        return AuthenticationError("The session has expired.", "SESSION_EXPIRED")
    if session.status is not SessionStatus.ACTIVE:
        return _invalid_session_error()
    return None


async def get_session_cache(request: Request) -> ValkeySessionCache:
    client = await get_valkey(request)
    return ValkeySessionCache(client)


async def get_current_session(
    request: Request,
    session: AsyncSession = Depends(get_db_session),
    cache: SessionCachePort = Depends(get_session_cache),
) -> Session:
    session_id = _session_id_from_cookie(request)
    if session_id is None:
        raise _invalid_session_error()
    now = utc_now()
    cached = await cache.get_session(session_id)
    if cached is not None:
        rejected = _rejected_cache_state(cached, now)
        if rejected is not None:
            raise rejected
    # Cache miss or cache-actively-valid -> authoritative Postgres row.
    record = await PostgresSessionRepository(session).find_by_id(session_id)
    if record is None:
        raise _invalid_session_error()
    rejected = _rejected_db_state(record, now)
    if rejected is not None:
        raise rejected
    # Write-through: the realtime gateway authenticates WS handshakes from the
    # cache ONLY (services/realtime src/auth/session_authenticator.ts), so the
    # authoritative validation refreshes the 5s fast-path entry here. This
    # keeps a session connectable long after login without extending the TTL
    # (doc 16 §125-126: cache is disposable; the recheck stays authoritative —
    # a replaced/expired session is rejected BEFORE this point, so the cache is
    # never re-warmed for a dead session).
    await cache.set_session(record)
    return record


async def get_optional_current_session(
    request: Request,
    session: AsyncSession = Depends(get_db_session),
    cache: SessionCachePort = Depends(get_session_cache),
) -> Session | None:
    """Non-raising twin for the recovery-mode guard: an invalid/missing session
    does not 401 by itself — the guarded endpoint decides (block only known
    recovery-mode accounts)."""
    try:
        return await get_current_session(request, session, cache)
    except AuthenticationError:
        return None


def _session_id_from_cookie(request: Request) -> UUID | None:
    raw = request.cookies.get(SESSION_COOKIE)
    if not raw:
        return None
    try:
        return UUID(raw)
    except ValueError:
        return None
