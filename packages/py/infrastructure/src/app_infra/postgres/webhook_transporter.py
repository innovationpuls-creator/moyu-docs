from __future__ import annotations

from typing import Any

import httpx


class PostgresWebhookTransporter:
    """HTTP transporter for webhook deliveries (httpx, timeout 10s)."""

    def __init__(self, transport: httpx.AsyncBaseTransport | None = None) -> None:
        self._transport = transport

    async def post(self, url: str, payload: bytes, headers: dict[str, str]) -> int:
        client_options: dict[str, Any] = {"timeout": 10.0}
        if self._transport is not None:
            client_options["transport"] = self._transport
        async with httpx.AsyncClient(**client_options) as client:
            try:
                response = await client.post(url, content=payload, headers=headers)
                return response.status_code
            except httpx.HTTPError:
                return 0
