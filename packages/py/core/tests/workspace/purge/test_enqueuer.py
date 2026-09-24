from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from app_core.workspace.application.purge.enqueuer import (
    PURGE_TASK_TYPE,
    LifecyclePurgeEnqueuer,
    purge_task_id,
)
from app_core.workspace.ports.purge import PurgeCandidate


class Candidates:
    def __init__(self, values):
        self.values = values

    async def candidates_before(self, now, limit):
        return self.values[:limit]


class Tasks:
    def __init__(self):
        self.tasks = []

    async def create(self, task):
        self.tasks.append(task)


@pytest.mark.asyncio
async def test_enqueuer_uses_deterministic_task_identity() -> None:
    workspace_id = uuid4()
    candidate = PurgeCandidate(workspace_id, datetime.now(UTC))
    tasks = Tasks()
    count = await LifecyclePurgeEnqueuer(Candidates([candidate]), tasks).enqueue(
        datetime.now(UTC), 10
    )
    assert count == 1
    assert tasks.tasks[0].task_id == purge_task_id(workspace_id)
    assert tasks.tasks[0].task_type == PURGE_TASK_TYPE
    assert tasks.tasks[0].input_ref == str(workspace_id)


@pytest.mark.asyncio
async def test_enqueuer_honors_scan_limit() -> None:
    candidates = Candidates(
        [PurgeCandidate(uuid4(), datetime.now(UTC)) for _ in range(2)]
    )
    tasks = Tasks()
    count = await LifecyclePurgeEnqueuer(candidates, tasks).enqueue(
        datetime.now(UTC), 1
    )
    assert count == 1
    assert len(tasks.tasks) == 1
