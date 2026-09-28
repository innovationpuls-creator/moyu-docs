from __future__ import annotations

import json
from uuid import uuid4

import pytest
import pytest_asyncio
from app_infra.nats.task_trigger import (
    NatsTaskTrigger,
    task_trigger_envelope,
    task_trigger_subject,
)
from nats.aio.client import Client as NATS

NATS_URL = "nats://127.0.0.1:4222"
DATABASE_URL = "postgresql+psycopg://torch@localhost:5432/dom_workspace_lifecycle_test"


def test_task_trigger_envelope_contains_identity_only() -> None:
    task_id = uuid4()
    envelope = task_trigger_envelope(task_id, "maintenance.reconcile")
    assert envelope["taskId"] == str(task_id)
    assert envelope["taskType"] == "maintenance.reconcile"
    assert envelope["version"] == "1.0.0"
    assert "occurredAt" in envelope
    assert "state" not in envelope
    assert task_trigger_subject("maintenance.reconcile") == (
        "work.tasks.maintenance_reconcile.trigger"
    )


@pytest_asyncio.fixture(scope="module")
async def nats_server() -> str:
    probe = NATS()
    try:
        await probe.connect(NATS_URL, connect_timeout=1, allow_reconnect=False)
    except Exception as exc:
        pytest.skip(f"NATS unavailable at {NATS_URL}: {exc}")
    await probe.drain()
    yield NATS_URL


@pytest.mark.asyncio
async def test_real_jetstream_duplicate_delivery(nats_server: str) -> None:
    nc = NATS()
    await nc.connect(nats_server)
    trigger = NatsTaskTrigger(nc)
    await trigger.ensure_stream()
    js = nc.jetstream()
    consumer = await js.pull_subscribe(
        "work.tasks.maintenance_reconcile.trigger", durable="test-trigger"
    )
    task_id = uuid4()
    await trigger.publish_task_trigger(task_id, "maintenance.reconcile")
    await trigger.publish_task_trigger(task_id, "maintenance.reconcile")
    messages = await consumer.fetch(2, timeout=5)
    assert len(messages) == 2
    assert [json.loads(message.data)["taskId"] for message in messages] == [
        str(task_id),
        str(task_id),
    ]
    for message in messages:
        await message.ack()
    await nc.close()
