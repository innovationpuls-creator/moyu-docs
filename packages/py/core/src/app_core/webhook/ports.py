from __future__ import annotations

from typing import Protocol
from uuid import UUID


class WebhookTransporter(Protocol):
    async def post(self, url: str, payload: bytes, headers: dict[str, str]) -> int: ...


class WebhookSubscriptionLoader(Protocol):
    async def fetch(
        self, workspace_id: UUID, subscription_id: UUID
    ) -> tuple[str, str] | None: ...


class WebhookDeadLetterPort(Protocol):
    """Dead-letter surface for webhook.deliver tasks (arch 10)."""

    async def count_failed(self, subscription_id: UUID) -> int: ...
    async def requeue_failed(self, subscription_id: UUID) -> int: ...
