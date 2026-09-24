"""Publish resource broadcast envelopes to NATS (realtime relay input)."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from nats.aio.client import Client as NATS

SUBJECT_PREFIX = "rt.broadcast"
SCHEMA_VERSION = "1.0.0"


def broadcast_subject(resource_id: UUID) -> str:
    return f"{SUBJECT_PREFIX}.{resource_id}"


def broadcast_envelope(
    resource_id: UUID,
    kind: str,
    payload: dict[str, Any],
    *,
    sequence: int | None = None,
) -> dict[str, Any]:
    return {
        "resourceId": str(resource_id),
        "kind": kind,
        "payload": payload,
        "sequence": sequence,
        "occurredAt": datetime.now(UTC).isoformat(),
        "schemaVersion": SCHEMA_VERSION,
    }


class NatsResourceBroadcastPublisher:
    """Thin publisher: writes envelopes only; delivery is at-least-once."""

    def __init__(self, client: NATS) -> None:
        self._client = client

    async def publish(
        self,
        resource_id: UUID,
        kind: str,
        payload: dict[str, Any],
        *,
        sequence: int | None = None,
    ) -> str:
        subject = broadcast_subject(resource_id)
        envelope = broadcast_envelope(resource_id, kind, payload, sequence=sequence)
        await self._client.publish(subject, json.dumps(envelope).encode())
        return subject
