"""Recovery-mode guard (plan Task 24): blocks every non-recovery endpoint for
``DeletionPending`` accounts with a 403 Permission envelope (FR-AUTH-032 /
BDD "Account Recovery Mode 下服务端权威拦截一切普通业务操作").

Applied app-wide in ``create_app`` so ALL current and future business routes
are protected by default. Allowed even in recovery mode (FR-AUTH-032 allowed
operations + pre-auth entry points):

- login / reauthenticate / logout (entry + recent-auth + the only session ops)
- GET /v1/auth/status (deletion status + grace period)
- POST /v1/auth/cancel-delete-account
- public pre-auth endpoints (register / verify-email / resend-verification /
  forgot-password / reset-password) and /healthz

Error mapping (new API-layer code, reported for Phase 9 registry alignment):
Permission / 403 / ``ACCOUNT_IN_RECOVERY_MODE`` (not yet in
contracts/errors/error-codes.yaml; messageKey falls back to the errorCode).

Boundary note: the guard resolves the actor through the SAME DI graph as the
routes (get_db_session / valkey overrides), so tests see the same session state
— a pure ASGI middleware would bypass dependency overrides, so the guard lives
at the dependency layer.
"""

from __future__ import annotations

from app_core.common.exceptions import PermissionDeniedError
from app_core.session.ports.session_cache import SessionCachePort
from app_infra.postgres.account_repository import PostgresAccountRepository
from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from api.dependencies.auth import (
    get_db_session,
    get_optional_current_session,
    get_session_cache,
)

RECOVERY_MODE_BLOCKED_CODE = "ACCOUNT_IN_RECOVERY_MODE"
RECOVERY_MODE_BLOCKED_MESSAGE = (
    "账号处于恢复模式（待删除状态），仅可查询删除状态、取消删除或退出登录"
)

# (method, path) pairs that stay reachable for a DeletionPending account:
# pre-auth entry points + FR-AUTH-032's allowed operations.
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
    if accounts is not None and accounts.account.is_in_recovery_mode():
        raise PermissionDeniedError(
            RECOVERY_MODE_BLOCKED_MESSAGE, RECOVERY_MODE_BLOCKED_CODE
        )
