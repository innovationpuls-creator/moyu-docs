"""Plan Task 20: FastAPI bootstrap — /healthz, security headers, error envelope.

BDD-aligned assertions for the application boundary:
- /healthz returns 200 with a healthy body;
- every response carries the security headers (nosniff, CSP, frame/anti-sniff);
- an undefined route produces the canonical ErrorEnvelope (not a bare 404).
"""

from __future__ import annotations

import uuid

from httpx import AsyncClient


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
