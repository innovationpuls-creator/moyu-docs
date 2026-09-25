from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace
from uuid import uuid4

import pytest
from app_core.operations.task.events import (
    TaskEvent,
    TaskEventEmitter,
    event_for_transition,
)


class Publisher:
    def __init__(self) -> None:
        self.events = []

    async def publish(self, event):
        self.events.append(event)


@pytest.mark.asyncio
async def test_transition_mapping_and_progress_coalescing():
    task = SimpleNamespace(
        task_id=uuid4(),
        task_type="demo",
        state="Running",
        stage="importing",
        progress_message_code="import.progress.reading",
        progress_current=2,
        progress_total=4,
        progress_percentage=Decimal("50.00"),
    )
    publisher = Publisher()
    emitter = TaskEventEmitter(publisher)
    await emitter.emit("TaskProgressUpdated", task)
    task.progress_current = 3
    task.progress_percentage = Decimal("75.00")
    await emitter.emit("TaskProgressUpdated", task)
    assert not publisher.events
    await emitter.emit("TaskSucceeded", task)
    assert [event.event_type for event in publisher.events] == [
        "TaskProgressUpdated",
        "TaskSucceeded",
    ]
    assert publisher.events[0].payload["current"] == 3
    assert publisher.events[0].payload["total"] == 4
    assert publisher.events[0].payload["percentage"] == 75.0


def test_unknown_event_type_rejected():
    with pytest.raises(ValueError):
        TaskEvent.create("Unknown", uuid4())


def test_transition_event_has_task_identity():
    task = SimpleNamespace(task_id=uuid4(), task_type="demo", state="Queued")
    event = event_for_transition("TaskQueued", task)
    assert event.aggregate_id == task.task_id
    assert event.subject == "event.task.queued.v1"
