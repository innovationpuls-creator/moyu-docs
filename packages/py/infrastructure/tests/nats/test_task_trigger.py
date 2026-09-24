from __future__ import annotations

import asyncio
import json
import socket
import subprocess
import time
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
async def nats_server():
    container = "dom-nats-test"
    subprocess.run(["docker", "rm", "-f", container], check=False, capture_output=True)
    try:
        subprocess.run(
            [
                "docker",
                "run",
                "-d",
                "--name",
                container,
                "-p",
                "4222:4222",
                "-p",
                "8222:8222",
                "nats:2.10-alpine",
                "-js",
            ],
            check=True,
            capture_output=True,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        pytest.skip(f"NATS Docker startup unavailable: {exc}")
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        with socket.socket() as probe:
            probe.settimeout(0.2)
            try:
                probe.connect(("127.0.0.1", 4222))
                break
            except OSError:
                await asyncio.sleep(0.2)
    else:
        subprocess.run(["docker", "rm", "-f", container], check=False)
        pytest.skip("NATS Docker container did not open port 4222")
    yield NATS_URL
    subprocess.run(["docker", "rm", "-f", container], check=False, capture_output=True)


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
