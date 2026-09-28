"""Real-NATS broadcast evidence against a separately managed NATS service."""

from __future__ import annotations

import json
import time
from uuid import uuid4

import pytest
import pytest_asyncio
from app_infra.nats.resource_broadcast_publisher import (
    NatsResourceBroadcastPublisher,
    broadcast_subject,
)
from nats.aio.client import Client as NATS

NATS_URL = "nats://localhost:4222"


@pytest_asyncio.fixture(scope="module")
async def nats_server() -> str:
    probe = NATS()
    try:
        await probe.connect(NATS_URL, connect_timeout=1, allow_reconnect=False)
    except Exception as exc:
        pytest.skip(f"NATS unavailable at {NATS_URL}: {exc}")
    await probe.drain()
    yield NATS_URL


@pytest_asyncio.fixture
async def nc(nats_server: str) -> NATS:
    client = NATS()
    await client.connect(nats_server)
    yield client
    await client.drain()


@pytest.mark.asyncio
async def test_broadcast_publish_reaches_subscriber(
    nc: NATS,
) -> None:
    resource_id = uuid4()
    received: list[dict] = []

    async def on_message(msg) -> None:
        received.append(json.loads(msg.data.decode()))

    sub = await nc.subscribe(subject=broadcast_subject(resource_id), cb=on_message)
    await nc.flush()
    publisher = NatsResourceBroadcastPublisher(nc)
    subject = await publisher.publish(
        resource_id,
        "op",
        {"journalSeq": 7},
        sequence=7,
    )
    assert subject == broadcast_subject(resource_id)
    await nc.flush()
    deadline = time.time() + 5
    while not received and time.time() < deadline:
        await nc.flush()
        time.sleep(0.1)
    assert len(received) == 1
    envelope = received[0]
    assert envelope["resourceId"] == str(resource_id)
    assert envelope["kind"] == "op"
    assert envelope["payload"]["journalSeq"] == 7
    await sub.unsubscribe()


@pytest.mark.asyncio
async def test_broadcast_delivers_duplicates_at_least_once(nc: NATS) -> None:
    resource_id = uuid4()
    received: list[dict] = []

    async def on_message(msg) -> None:
        received.append(json.loads(msg.data.decode()))

    sub = await nc.subscribe(subject=broadcast_subject(resource_id), cb=on_message)
    await nc.flush()
    publisher = NatsResourceBroadcastPublisher(nc)
    for _ in range(2):
        await publisher.publish(resource_id, "op", {"i": 1}, sequence=1)
    await nc.flush()
    deadline = time.time() + 5
    while len(received) < 2 and time.time() < deadline:
        await nc.flush()
        time.sleep(0.1)
    assert len(received) == 2  # at-least-once delivery of both publishes
    await sub.unsubscribe()
