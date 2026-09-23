"""Recovery-mode guard (plan Task 24): blocks every non-recovery endpoint for
``DeletionPending`` accounts with a 403 Permission envelope (FR-AUTH-032 /
BDD "Account Recovery Mode 下服务端权威拦截一切普通业务操作").

Applied app-wide in ``create_app`` so ALL current and future business routes
are protected by default. Allowed even in recovery mode (FR-AUTH-032 allowed
operations + pre-auth entry points):

- login / reauthenticate / logout (entry + recent-auth + the only session ops)
- GET /v1/auth/status (deletion status + grace period)
- POST /v1/auth/cancel-delete-account
- POST /v1/auth/delete-account ONLY as an idempotent REPLAY (a COMPLETED
  Idempotency-Key returns the stored original response; a fresh key while in
  recovery mode stays blocked — replaying is not a new business operation)
- public pre-auth endpoints (register / verify-email / resend-verification /
  forgot-password / reset-password) and /healthz

Error mapping: Permission / 403 / ``ACCOUNT_IN_RECOVERY_MODE`` (registered in
contracts/errors/error-codes.yaml, messageKey auth.error.accountInRecoveryMode;
the error handler resolves category/messageKey from the catalog).

Boundary note: the guard resolves the actor through the SAME DI graph as the
routes (get_db_session / valkey overrides), so tests see the same session state
— a pure ASGI middleware would bypass dependency overrides, so the guard lives
at the dependency layer.

Accepted trade-off (review item 4.4): for a guarded request the guard performs
one authoritative Postgres round-trip (accounts.find_by_account_id) to decide
recovery mode, plus a second one only when a delete-account request carries an
Idempotency-Key. That is a deliberate, documented cost: the Valkey session
cache is disposable and not a trusted store for account status (doc 16 §125),
so account state must be read from the source of truth. A recovery-flag cache
would reintroduce staleness at the cost of a second cache to invalidate —
deferred unless profiling shows it matters.
"""

from __future__ import annotations

from uuid import UUID

from app_core.account.ports.idempotency_repository import (
    IdempotencyRecord,
    IdempotencyState,
)
from app_core.common.exceptions import PermissionDeniedError
from app_core.session.ports.session_cache import SessionCachePort
from app_infra.postgres.account_repository import PostgresAccountRepository
from app_infra.postgres.idempotency_repository import PostgresIdempotencyRepository
from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from api.dependencies.auth import (
    deletion_idempotency_key,
    get_db_session,
    get_optional_current_session,
    get_session_cache,
)

RECOVERY_MODE_BLOCKED_CODE = "ACCOUNT_IN_RECOVERY_MODE"
RECOVERY_MODE_BLOCKED_MESSAGE = (
    "账号处于恢复模式（待删除状态），仅可查询删除状态、取消删除或退出登录"
)

# (method, path) pairs that stay reachable for a DeletionPending account:
# pre-auth entry points + FR-AUTH-032's allowed operations. delete-account is
# NOT listed: it is kept blocked for fresh keys — only a COMPLETED idempotency
# replay passes (see _is_completed_delete_replay).
_RECOVERY_ALLOWED_METHOD_PATHS: frozenset[tuple[str, str]] = frozenset(
    {
        ("GET", "/healthz"),
        ("POST", "/v1/auth/register"),
        ("POST", "/v1/auth/verify-email"),
        ("POST", "/v1/auth/resend-verification"),
        ("POST", "/v1/auth/login"),
        ("POST", "/v1/auth/forgot-password"),
        ("POST", "/v1/auth/reset-password"),
        ("POST", "/v1/auth/reauthenticate"),
        ("POST", "/v1/auth/logout"),
        ("GET", "/v1/auth/status"),
        ("POST", "/v1/auth/cancel-delete-account"),
    }
)

_DELETE_ACCOUNT = ("POST", "/v1/auth/delete-account")


async def _is_completed_delete_replay(
    request: Request, account_id: UUID, session: AsyncSession
) -> bool:
    """True when the request replays a COMPLETED delete-account idempotency
    key: the route then returns the stored original response instead of
    executing a new business operation (FR-AUTH-032 preserved)."""
    header_key = request.headers.get("Idempotency-Key")
    if not header_key:
        return False
    record = await PostgresIdempotencyRepository(session).get(
        deletion_idempotency_key(account_id, header_key)
    )
    return (
        isinstance(record, IdempotencyRecord)
        and record.state is IdempotencyState.COMPLETED
        and bool(record.response)
    )


async def get_recovery_guard(
    request: Request,
    session: AsyncSession = Depends(get_db_session),
    cache: SessionCachePort = Depends(get_session_cache),
) -> None:
    if (request.method, request.url.path) in _RECOVERY_ALLOWED_METHOD_PATHS:
        return
    # Only business paths are guarded (docs / openapi are dev surfaces).
    if not request.url.path.startswith("/v1/"):
        return
    current = await get_optional_current_session(request, session, cache)
    if current is None:
        return  # unauthenticated -> the route's own get_current_session 401s
    accounts = await PostgresAccountRepository(session).find_by_account_id(
        current.account_id
    )
    if accounts is None or not accounts.account.is_in_recovery_mode():
        return
    if (
        request.method,
        request.url.path,
    ) == _DELETE_ACCOUNT and await _is_completed_delete_replay(
        request, current.account_id, session
    ):
        return  # idempotent replay of an already-executed deletion request
    raise PermissionDeniedError(
        RECOVERY_MODE_BLOCKED_MESSAGE, RECOVERY_MODE_BLOCKED_CODE
    )
