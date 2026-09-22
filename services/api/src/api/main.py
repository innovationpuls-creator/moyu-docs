"""FastAPI application factory for the DOM API service (plan Task 20).

``create_app`` wires the error-envelope handlers, security headers, health
probe, the /v1/auth route group and the recovery-mode guard (Task 24, applied
app-wide so DeletionPending accounts are blocked from every business route).
Tests pass ``debug=True`` (cookies not Secure, dependency overrides) and use
``overrides`` or ``app.dependency_overrides`` to point the DB session / Valkey
/ mailer / workspace-ownership at test resources.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from fastapi import Depends, FastAPI

from api.config import settings
from api.middleware.error_handler import register_error_handlers
from api.middleware.recovery_mode_guard import get_recovery_guard
from api.middleware.security_headers import SecurityHeadersMiddleware
from api.routes.auth_deletion import router as auth_deletion_router
from api.routes.auth_password import router as auth_password_router
from api.routes.auth_registration import router as auth_registration_router
from api.routes.auth_session import router as auth_session_router


def create_app(
    *,
    debug: bool = False,
    overrides: Mapping[Any, Any] | None = None,
) -> FastAPI:
    settings.debug = debug
    app = FastAPI(
        title="DOM API",
        version="0.1.0",
        debug=debug,
        # FR-AUTH-032: app-wide guard blocks all non-recovery endpoints for
        # DeletionPending accounts; allowed paths short-circuit inside.
        dependencies=[Depends(get_recovery_guard)],
    )
    app.add_middleware(SecurityHeadersMiddleware)
    register_error_handlers(app)

    app.include_router(auth_registration_router, prefix="/v1/auth")
    app.include_router(auth_session_router, prefix="/v1/auth")
    app.include_router(auth_password_router, prefix="/v1/auth")
    app.include_router(auth_deletion_router, prefix="/v1/auth")

    @app.get("/healthz")
    async def healthz() -> dict[str, str]:
        return {"status": "ok"}

    if overrides:
        for dependency, override in overrides.items():
            app.dependency_overrides[dependency] = override
    return app
