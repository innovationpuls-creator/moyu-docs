"""FastAPI application factory for the DOM API service (plan Task 20).

``create_app`` wires the error-envelope handlers, security headers, health
probe and the /v1/auth route group. Tests pass ``debug=True`` (cookies not
Secure, dependency overrides) and use ``overrides`` or
``app.dependency_overrides`` to point the DB session / Valkey / mailer at test
resources.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from fastapi import FastAPI

from api.config import settings
from api.middleware.error_handler import register_error_handlers
from api.middleware.security_headers import SecurityHeadersMiddleware
from api.routes.auth_registration import router as auth_registration_router


def create_app(
    *,
    debug: bool = False,
    overrides: Mapping[Any, Any] | None = None,
) -> FastAPI:
    settings.debug = debug
    app = FastAPI(title="DOM API", version="0.1.0", debug=debug)
    app.add_middleware(SecurityHeadersMiddleware)
    register_error_handlers(app)

    app.include_router(auth_registration_router, prefix="/v1/auth")

    @app.get("/healthz")
    async def healthz() -> dict[str, str]:
        return {"status": "ok"}

    if overrides:
        for dependency, override in overrides.items():
            app.dependency_overrides[dependency] = override
    return app
