from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Protocol
from uuid import UUID, uuid4


@dataclass(frozen=True)
class LifecycleEvent:
    event_type: str
    event_subject: str
    aggregate_id: UUID
    payload: dict[str, Any]
    occurred_at: datetime
    event_id: UUID

    @classmethod
    def create(
        cls,
        event_type: str,
        event_subject: str,
        aggregate_id: UUID,
        payload: dict[str, Any],
        *,
        occurred_at: datetime | None = None,
    ) -> LifecycleEvent:
        return cls(
            event_type=event_type,
            event_subject=event_subject,
            aggregate_id=aggregate_id,
            payload=payload,
            occurred_at=occurred_at or datetime.now(UTC),
            event_id=uuid4(),
        )


class LifecycleEventPublisher(Protocol):
    async def publish(self, event: LifecycleEvent) -> None: ...
