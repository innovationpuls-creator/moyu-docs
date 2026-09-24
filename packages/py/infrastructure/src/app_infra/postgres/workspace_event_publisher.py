from __future__ import annotations

from uuid import uuid4

from app_core.workspace.ports.events import LifecycleEvent
from sqlalchemy import JSON, bindparam, text
from sqlalchemy.ext.asyncio import AsyncSession


class PostgresLifecycleEventPublisher:
    """Write lifecycle facts to the caller-owned transactional outbox."""

    def __init__(self, session: AsyncSession, *, producer: str = "core.workspace"):
        self._session = session
        self._producer = producer

    async def publish(self, event: LifecycleEvent) -> None:
        payload = {
            "eventId": str(event.event_id),
            "eventType": event.event_type,
            "schemaVersion": "1.0.0",
            "occurredAt": event.occurred_at.isoformat(),
            "producer": self._producer,
            "payload": event.payload,
        }
        await self._session.execute(
            text(
                "INSERT INTO integration.outbox_events "
                "(outbox_id, event_id, event_type, schema_version, aggregate_type, "
                "aggregate_id, payload, created_at) "
                "VALUES (:outbox_id, :event_id, :event_type, :schema_version, "
                ":aggregate_type, :aggregate_id, :payload, :created_at) "
                "ON CONFLICT (event_id) DO NOTHING"
            ).bindparams(bindparam("payload", type_=JSON)),
            {
                "event_id": event.event_id,
                "event_type": event.event_subject,
                "schema_version": "1.0.0",
                "outbox_id": uuid4(),
                "aggregate_type": event.event_type.removesuffix("Created")
                .removesuffix("Archived")
                .removesuffix("Unarchived")
                .removesuffix("Trashed")
                .removesuffix("Restored"),
                "aggregate_id": event.aggregate_id,
                "payload": payload,
                "created_at": event.occurred_at,
            },
        )
