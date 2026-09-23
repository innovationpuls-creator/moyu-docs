"""Plan Task 20: FastAPI bootstrap — /healthz, security headers, error envelope.

BDD-aligned assertions for the application boundary:
- /healthz returns 200 with a healthy body;
- every response carries the security headers (nosniff, CSP, frame/anti-sniff);
- an undefined route produces the canonical ErrorEnvelope (not a bare 404);
- an unhandled route exception produces the generic Internal envelope with no
  internals leaked (doc 28 §31).
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from api.dependencies.auth import get_db_session, get_valkey
from api.main import create_app
from httpx import ASGITransport, AsyncClient
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession


async def test_healthz_returns_200_with_healthy_body(api_client: AsyncClient) -> None:
    response = await api_client.get("/healthz")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"


async def test_healthz_carries_security_headers(api_client: AsyncClient) -> None:
    response = await api_client.get("/healthz")

    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["content-security-policy"] == "default-src 'self'"
    assert response.headers["x-frame-options"] == "DENY"
    assert response.headers["referrer-policy"] == "no-referrer"


async def test_undefined_route_returns_error_envelope_404(
    api_client: AsyncClient,
) -> None:
    response = await api_client.get("/definitely/not/a/route")

    assert response.status_code == 404
    body = response.json()
    assert body["category"] == "NotFound"
    assert body["errorCode"] == "NOT_FOUND"
    assert body["messageKey"] == "NOT_FOUND"
    assert body["retryable"] is False
    uuid.UUID(body["requestId"])  # must parse as a UUID


@asynccontextmanager
async def _envelope_app(
    db_session: AsyncSession, valkey_client: Redis
) -> AsyncIterator[AsyncClient]:
    """App under test with the standard error handler + a route guaranteed to
    raise an unhandled exception. debug=False so the production envelope path
    is exercised (FastAPI routes the Exception handler to ServerErrorMiddleware,
    which re-raises instead when debug=True)."""
    app = create_app(debug=False)
    app.dependency_overrides[get_db_session] = lambda: db_session
    app.dependency_overrides[get_valkey] = lambda: valkey_client

    @app.get("/v1/_boom")
    async def _boom() -> None:
        raise RuntimeError("postgres password: hunter2-secret")

    # raise_app_exceptions=False: ServerErrorMiddleware deliberately re-raises
    # after sending the 500 envelope (for server-side logging); the test client
    # must return the envelope instead of propagating the exception.
    async with AsyncClient(
        transport=ASGITransport(app=app, raise_app_exceptions=False),
        base_url="http://test",
    ) as client:
        yield client


async def test_unhandled_route_exception_returns_internal_envelope(
    db_session: AsyncSession,
    valkey_client: Redis,
) -> None:
    """doc 28 §31: an unhandled exception must surface as the generic Internal
    envelope — category Internal, requestId present, NO stack trace and NO
    internals (exception message / secrets) leaked to the client."""
    async with _envelope_app(db_session, valkey_client) as client:
        response = await client.get("/v1/_boom")

    assert response.status_code == 500
    body = response.json()
    assert body["category"] == "Internal"
    assert body["errorCode"] == "INTERNAL_ERROR"
    uuid.UUID(body["requestId"])
    assert "hunter2-secret" not in response.text  # no internals leaked
    assert "Traceback" not in response.text
    assert "RuntimeError" not in response.text
