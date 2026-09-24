from __future__ import annotations

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
    task = SimpleNamespace(task_id=uuid4(), task_type="demo", state="Running")
    publisher = Publisher()
    emitter = TaskEventEmitter(publisher)
    await emitter.emit("TaskProgressUpdated", task, payload={"progress": 1})
    await emitter.emit("TaskProgressUpdated", task, payload={"progress": 2})
    assert not publisher.events
    await emitter.emit("TaskSucceeded", task)
    assert [event.event_type for event in publisher.events] == [
        "TaskProgressUpdated",
        "TaskSucceeded",
    ]
    assert publisher.events[0].payload["progress"] == 2


def test_unknown_event_type_rejected():
    with pytest.raises(ValueError):
        TaskEvent.create("Unknown", uuid4())


def test_transition_event_has_task_identity():
    task = SimpleNamespace(task_id=uuid4(), task_type="demo", state="Queued")
    event = event_for_transition("TaskQueued", task)
    assert event.aggregate_id == task.task_id
    assert event.subject == "event.task.queued.v1"
