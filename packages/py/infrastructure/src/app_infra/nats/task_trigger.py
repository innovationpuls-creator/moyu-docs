from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from nats.aio.client import Client as NATS

SUBJECT_PREFIX = "work.tasks"
STREAM_NAME = "WORK_TASK_TRIGGERS"
STREAM_SUBJECT = f"{SUBJECT_PREFIX}.>"
SCHEMA_VERSION = "1.0.0"


def task_trigger_subject(task_type: str) -> str:
    safe_type = task_type.replace(".", "_").replace(">", "_").replace("*", "_")
    return f"{SUBJECT_PREFIX}.{safe_type}.trigger"


def task_trigger_envelope(task_id: UUID, task_type: str) -> dict[str, Any]:
    return {
        "taskId": str(task_id),
        "taskType": task_type,
        "version": SCHEMA_VERSION,
        "occurredAt": datetime.now(UTC).isoformat(),
    }


class NatsTaskTrigger:
    def __init__(self, client: NATS) -> None:
        self._client = client

    async def ensure_stream(self) -> None:
        js = self._client.jetstream()
        try:
            await js.stream_info(STREAM_NAME)
        except Exception:
            await js.add_stream(name=STREAM_NAME, subjects=[STREAM_SUBJECT])

    async def publish_task_trigger(self, task_id: UUID, task_type: str) -> None:
        await self.ensure_stream()
        await self._client.jetstream().publish(
            task_trigger_subject(task_type),
            json.dumps(task_trigger_envelope(task_id, task_type)).encode(),
        )
