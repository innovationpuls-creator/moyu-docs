from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Protocol
from uuid import UUID, uuid4

_EVENT_SUBJECTS = {
    "TaskCreated": "event.task.created.v1",
    "TaskQueued": "event.task.queued.v1",
    "TaskStarted": "event.task.started.v1",
    "TaskWaitingForUser": "event.task.waiting-for-user.v1",
    "TaskRetryScheduled": "event.task.retry-scheduled.v1",
    "TaskSucceeded": "event.task.succeeded.v1",
    "TaskPartiallySucceeded": "event.task.partially-succeeded.v1",
    "TaskFailed": "event.task.failed.v1",
    "TaskCancelled": "event.task.cancelled.v1",
    "TaskProgressUpdated": "event.task.progress-updated.v1",
}


@dataclass(frozen=True)
class TaskEvent:
    event_id: UUID
    event_type: str
    subject: str
    aggregate_id: UUID
    occurred_at: datetime
    payload: dict[str, Any]

    @classmethod
    def create(
        cls,
        event_type: str,
        task_id: UUID,
        payload: dict[str, Any] | None = None,
        *,
        occurred_at: datetime | None = None,
    ) -> TaskEvent:
        try:
            subject = _EVENT_SUBJECTS[event_type]
        except KeyError as exc:
            raise ValueError(f"unknown task event type: {event_type}") from exc
        return cls(
            uuid4(),
            event_type,
            subject,
            task_id,
            occurred_at or datetime.now(UTC),
            payload or {},
        )


class TaskEventPublisher(Protocol):
    async def publish(self, event: TaskEvent) -> None: ...


def event_for_transition(
    event_type: str, task: Any, *, payload: dict[str, Any] | None = None
) -> TaskEvent:
    return TaskEvent.create(
        event_type,
        task.task_id,
        {
            "taskId": str(task.task_id),
            "taskType": task.task_type,
            "state": getattr(task.state, "value", task.state),
            **(payload or {}),
        },
        occurred_at=getattr(task, "updated_at", None),
    )


class TaskEventEmitter:
    """Maps state transitions to facts and coalesces progress by task."""

    def __init__(self, publisher: TaskEventPublisher) -> None:
        self._publisher = publisher
        self._progress: dict[UUID, TaskEvent] = {}

    async def emit(
        self,
        event_type: str,
        task: Any,
        *,
        payload: dict[str, Any] | None = None,
    ) -> None:
        event = event_for_transition(event_type, task, payload=payload)
        if event_type == "TaskProgressUpdated":
            self._progress[event.aggregate_id] = event
            return
        pending = self._progress.pop(event.aggregate_id, None)
        if pending is not None:
            await self._publisher.publish(pending)
        await self._publisher.publish(event)

    async def flush_progress(self, task_id: UUID) -> None:
        pending = self._progress.pop(task_id, None)
        if pending is not None:
            await self._publisher.publish(pending)
