from __future__ import annotations

from datetime import datetime
from typing import Protocol
from uuid import UUID, uuid5

from app_core.workspace.application.purge import PurgePolicy
from app_core.workspace.ports.purge import PurgeCandidate

PURGE_TASK_NAMESPACE = UUID("6c75b5ab-3a4e-4c53-bf0a-5b6e0f8c3e3a")
PURGE_TASK_TYPE = "lifecycle.purge.workspace"


class PurgeCandidateRepository(Protocol):
    async def candidates_before(
        self, now: datetime, limit: int
    ) -> list[PurgeCandidate]: ...


class PurgeTaskRepository(Protocol):
    async def create(self, task: object) -> None: ...


class LifecyclePurgeEnqueuer:
    def __init__(
        self,
        candidates: PurgeCandidateRepository,
        tasks: PurgeTaskRepository,
    ) -> None:
        self._candidates = candidates
        self._tasks = tasks

    async def enqueue(self, now: datetime, limit: int) -> int:
        eligible = await self._candidates.candidates_before(now, limit)
        for candidate in eligible:
            task = _purge_task(candidate)
            await self._tasks.create(task)
        return len(eligible)


def purge_task_id(workspace_id: UUID) -> UUID:
    return uuid5(PURGE_TASK_NAMESPACE, f"lifecycle.purge.workspace:{workspace_id}")


def _purge_task(candidate: PurgeCandidate) -> object:
    from task_runtime.domain import Priority, Task

    task = Task(
        task_id=purge_task_id(candidate.workspace_id),
        task_type=PURGE_TASK_TYPE,
        priority=Priority.MAINTENANCE,
        input_ref=str(candidate.workspace_id),
    )
    task.queue()
    task.stage = "workspace-purge"
    return task


def purge_payload(candidate: PurgeCandidate) -> dict[str, str]:
    return PurgePolicy.payload(candidate).as_dict()
