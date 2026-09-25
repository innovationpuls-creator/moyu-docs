"""webhook.deliver task consumer (arch 10 worker side)."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Protocol
from uuid import UUID

from app_core.webhook.application import DeliverWebhook
from app_core.webhook.domain import WebhookEvent
from task_runtime.domain import RetryableTaskError


class _Context(Protocol):
    task: _Input

    async def checkpoint(self) -> None: ...


TASK_TYPE = "webhook.deliver"


class _Input(Protocol):
    @property
    def input_ref(self) -> str | None: ...


class WebhookDeliverHandler:
    def __init__(self, deliver: DeliverWebhook) -> None:
        self._deliver = deliver

    async def execute(self, context: _Context) -> None:
        task = context.task
        payload = json.loads(task.input_ref or "{}")
        occurred_at = datetime.now(timezone.utc)
        event = WebhookEvent(
            kind=str(payload["event"]),
            workspace_id=str(payload["workspaceId"]),
            occurred_at=occurred_at,
        )
        try:
            result = await self._deliver.execute(
                UUID(payload["workspaceId"]),
                UUID(payload["subscriptionId"]),
                event,
            )
        except Exception as exc:
            raise RetryableTaskError("WEBHOOK_DELIVERY_FAILED") from exc
        if not result.delivered:
            # Non-2xx/transport failures are retryable (backoff on the runner).
            raise RetryableTaskError("WEBHOOK_DELIVERY_REJECTED")
        await context.checkpoint()


def webhook_deliver_input(ref: str) -> dict[str, object]:
    """Decode the task input ref (JSON) into handler-input fields."""
    payload = json.loads(ref)
    return {
        "subscription_id": UUID(payload["subscriptionId"]),
        "workspace_id": UUID(payload["workspaceId"]),
        "event": str(payload["event"]),
    }
