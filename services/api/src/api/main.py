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
from api.logging import configure_logging
from api.middleware.error_handler import register_error_handlers
from api.middleware.recovery_mode_guard import get_recovery_guard
from api.middleware.request_context import RequestContextMiddleware
from api.middleware.security_headers import SecurityHeadersMiddleware
from api.routes.ai_changesets import router as ai_changesets_router
from api.routes.assets import router as assets_router
from api.routes.auth_deletion import router as auth_deletion_router
from api.routes.auth_password import router as auth_password_router
from api.routes.auth_registration import router as auth_registration_router
from api.routes.auth_session import router as auth_session_router
from api.routes.comments import router as comments_router
from api.routes.diagnostics import router as diagnostics_router
from api.routes.history import router as history_router
from api.routes.importexport import router as importexport_router
from api.routes.integrations import router as integrations_router
from api.routes.member_suggestions import router as member_suggestions_router
from api.routes.notifications import router as notifications_router
from api.routes.project_listing import router as project_listing_router
from api.routes.public_api import router as public_api_router
from api.routes.resource_diff import router as resource_diff_router
from api.routes.resource_listing import router as resource_listing_router
from api.routes.resource_open import router as resource_open_router
from api.routes.resource_write import router as resource_write_router
from api.routes.search import router as search_router
from api.routes.webhooks import router as webhooks_router
from api.routes.workspace import router as workspace_router
from api.routes.workspace_listing import router as workspace_listing_router
from api.routes.workspace_ownership import router as workspace_ownership_router


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
    if debug:
        # Structured correlation + access logging (arch 23); worker/prod runs
        # configure this via api.logging.configure_logging at boot.
        configure_logging()
        app.add_middleware(RequestContextMiddleware)
    app.add_middleware(SecurityHeadersMiddleware)
    register_error_handlers(app)

    app.include_router(auth_registration_router, prefix="/v1/auth")
    app.include_router(auth_session_router, prefix="/v1/auth")
    app.include_router(auth_password_router, prefix="/v1/auth")
    app.include_router(auth_deletion_router, prefix="/v1/auth")
    app.include_router(workspace_ownership_router, prefix="/v1/auth")
    app.include_router(workspace_router, prefix="/v1")
    app.include_router(workspace_listing_router, prefix="/v1")
    app.include_router(resource_open_router, prefix="/v1")
    app.include_router(resource_write_router, prefix="/v1")
    app.include_router(diagnostics_router, prefix="/v1")
    app.include_router(comments_router, prefix="/v1")
    app.include_router(member_suggestions_router, prefix="/v1")
    app.include_router(search_router, prefix="/v1")
    app.include_router(webhooks_router, prefix="/v1")
    app.include_router(importexport_router, prefix="/v1")
    app.include_router(assets_router, prefix="/v1")
    app.include_router(ai_changesets_router, prefix="/v1")
    app.include_router(integrations_router, prefix="/v1")
    app.include_router(history_router, prefix="/v1")
    app.include_router(notifications_router, prefix="/v1")
    app.include_router(public_api_router, prefix="/v1")
    app.include_router(resource_diff_router, prefix="/v1")
    app.include_router(project_listing_router, prefix="/v1")
    app.include_router(resource_listing_router, prefix="/v1")

    @app.get("/healthz")
    async def healthz() -> dict[str, str]:
        return {"status": "ok"}

    if overrides:
        for dependency, override in overrides.items():
            app.dependency_overrides[dependency] = override
    return app
