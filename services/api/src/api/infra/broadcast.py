"""Lazy NATS broadcast publisher for realtime op relay (dev/prod same
client; connection established on first use)."""

from __future__ import annotations

import asyncio

from app_infra.nats.resource_broadcast_publisher import (
    NatsResourceBroadcastPublisher,
)
from nats.aio.client import Client as NATS

NATS_URL = "nats://localhost:4222"


class BroadcastRelayUnavailable(RuntimeError):
    """NATS unreachable: the save still persisted; the realtime relay is down."""


_client: NATS | None = None
_lock = asyncio.Lock()


async def get_nats_client() -> NATS:
    global _client
    if _client is None:
        async with _lock:
            if _client is None:
                client = NATS()
                try:
                    await client.connect(
                        NATS_URL, connect_timeout=2, allow_reconnect=False
                    )
                except Exception as exc:
                    raise BroadcastRelayUnavailable(str(exc)) from exc
                _client = client
    assert _client is not None
    return _client


async def get_broadcast_publisher() -> NatsResourceBroadcastPublisher:
    return NatsResourceBroadcastPublisher(await get_nats_client())
