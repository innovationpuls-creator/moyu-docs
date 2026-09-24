from __future__ import annotations

from uuid import UUID

from app_core.webhook import domain
from app_core.webhook.domain import WebhookDelivery, WebhookEvent
from app_core.webhook.ports import (
    WebhookDeadLetterPort,
    WebhookSubscriptionLoader,
    WebhookTransporter,
)


class DeliverWebhook:
    """Worker-side deliver (arch 10): sign the event and POST it."""

    def __init__(
        self, loader: WebhookSubscriptionLoader, transporter: WebhookTransporter
    ) -> None:
        self._loader = loader
        self._transporter = transporter

    async def execute(
        self, workspace_id: UUID, subscription_id: UUID, event: WebhookEvent
    ) -> WebhookDelivery:
        fetched = await self._loader.fetch(workspace_id, subscription_id)
        if fetched is None:
            raise domain.WebhookNotFound()
        url, secret_key_hex = fetched
        payload, headers = domain.signed_headers(event, secret_key_hex)
        status_code = await self._transporter.post(url, payload, headers)
        return WebhookDelivery(delivered=status_code < 400, status_code=status_code)


class RequeueResult:
    def __init__(self, requeued: int, remainingFailed: int) -> None:
        self.requeued = requeued
        self.remainingFailed = remainingFailed


class RequeueWebhookDeliveries:
    """Arch 10 dead-letter replay: a Failed delivery is requeued as a fresh
    Queued task carrying the original inputs."""

    def __init__(self, dead_letters: WebhookDeadLetterPort) -> None:
        self._dead_letters = dead_letters

    async def execute(self, subscription_id: UUID) -> RequeueResult:
        requeued = await self._dead_letters.requeue_failed(subscription_id)
        remaining = await self._dead_letters.count_failed(subscription_id)
        return RequeueResult(requeued=requeued, remainingFailed=remaining)
