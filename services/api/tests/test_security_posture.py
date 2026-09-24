"""Arch 21: security posture suite (no DB needed)."""

from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest
from api.dependencies.auth import get_current_session
from api.main import create_app
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

REQUIRED_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "Content-Security-Policy": None,  # present, CSP value flexible
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "Permissions-Policy": None,
    "Cross-Origin-Opener-Policy": "same-origin",
    "Cross-Origin-Resource-Policy": "same-origin",
}


@pytest.mark.asyncio
async def test_every_response_carries_security_headers() -> None:
    app: FastAPI = create_app(debug=True)
    app.dependency_overrides[get_current_session] = lambda: SimpleNamespace(
        account_id=uuid.uuid4()
    )
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        ok = await client.get("/healthz")
        missing = await client.get("/does-not-exist-xyz")
    for response in (ok, missing):
        for header, expected in REQUIRED_HEADERS.items():
            assert header in response.headers, (
                f"{header} missing on {response.status_code}"
            )
            if expected is not None:
                assert response.headers[header] == expected


@pytest.mark.asyncio
async def test_error_envelope_never_leaks_internals() -> None:
    app: FastAPI = create_app(debug=True)
    app.dependency_overrides[get_current_session] = lambda: SimpleNamespace(
        account_id=uuid.uuid4()
    )
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get(f"/v1/resources/{uuid.uuid4()}")
    body = response.json()
    assert "traceback" not in str(body).lower()
    assert "exc" not in str(body).lower()
    assert "stack" not in str(body).lower()
    assert response.status_code == 404
