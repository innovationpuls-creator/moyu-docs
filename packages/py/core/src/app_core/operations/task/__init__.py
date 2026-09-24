from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Protocol, cast
from uuid import UUID

from task_runtime.domain import StaleAttemptError


class TaskLike(Protocol):
    task_id: UUID
    task_type: str

    def queue(self) -> None: ...

    def recover(self) -> None: ...

    def succeed(self) -> None: ...

    def fail(self) -> None: ...


class TaskRepository(Protocol):
    async def create(self, task: TaskLike) -> bool: ...

    async def get(self, task_id: UUID) -> TaskLike | None: ...

    async def save(self, task: TaskLike) -> None: ...

    async def claim(
        self, task_id: UUID, worker_id: str, lease_seconds: int
    ) -> object: ...

    async def heartbeat(
        self, task_id: UUID, attempt_id: UUID, epoch: int, lease_seconds: int
    ) -> bool: ...

    async def schedule_retry(
        self, task_id: UUID, next_attempt_at: datetime, failure_code: str
    ) -> None: ...

    async def request_cancel(self, task_id: UUID, requested_at: datetime) -> None: ...


class TaskEventPublisher(Protocol):
    async def publish(self, event_type: str, task: TaskLike) -> None: ...


class CreateTask:
    def __init__(
        self,
        repository: TaskRepository,
        *,
        task_factory: Callable[[str], object] | None = None,
    ) -> None:
        self._repository = repository
        self._task_factory = task_factory

    async def execute(
        self,
        task_type: str,
        *,
        task_id: UUID | None = None,
        input_ref: str | None = None,
    ) -> TaskLike:
        if self._task_factory is None:
            from task_runtime.domain import Task

            task = cast(TaskLike, Task.create(task_type))
            if task_id is not None:
                task.task_id = task_id
            if input_ref is not None:
                task.input_ref = input_ref  # type: ignore[attr-defined]
        else:
            task = cast(TaskLike, self._task_factory(task_type))
        task.queue()
        created = await self._repository.create(task)
        if created is False:
            existing = await self._repository.get(task.task_id)
            if existing is None:
                raise RuntimeError("task identity conflict without existing row")
            return existing
        return task


class ClaimTask:
    def __init__(self, repository: TaskRepository) -> None:
        self._repository = repository

    async def execute(
        self, task_id: UUID, worker_id: str, lease_seconds: int
    ) -> object:
        return await self._repository.claim(task_id, worker_id, lease_seconds)


class Heartbeat:
    def __init__(self, repository: TaskRepository) -> None:
        self._repository = repository

    async def execute(
        self, task_id: UUID, attempt_id: UUID, epoch: int, lease_seconds: int
    ) -> None:
        accepted = await self._repository.heartbeat(
            task_id, attempt_id, epoch, lease_seconds
        )
        if not accepted:
            raise StaleAttemptError("attempt is no longer authoritative")


class ScheduleRetry:
    def __init__(self, repository: TaskRepository) -> None:
        self._repository = repository

    async def execute(
        self, task_id: UUID, *, delay_seconds: int, failure_code: str
    ) -> None:
        await self._repository.schedule_retry(
            task_id,
            datetime.now(UTC) + timedelta(seconds=delay_seconds),
            failure_code,
        )


class FinishAttempt:
    def __init__(self, repository: TaskRepository) -> None:
        self._repository = repository

    async def execute(
        self, task_id: UUID, attempt_id: UUID, epoch: int, *, succeeded: bool
    ) -> None:
        task = await self._repository.get(task_id)
        if (
            task is None
            or getattr(task, "current_attempt_id", attempt_id) != attempt_id
        ):
            raise StaleAttemptError("attempt is no longer authoritative")
        if getattr(task, "execution_epoch", epoch) != epoch:
            raise StaleAttemptError("execution epoch is stale")
        if succeeded:
            task.succeed()
        else:
            task.fail()
        await self._repository.save(task)


class RequestCancel:
    def __init__(self, repository: TaskRepository) -> None:
        self._repository = repository

    async def execute(self, task_id: UUID) -> None:
        await self._repository.request_cancel(task_id, datetime.now(UTC))


class ResumeTask:
    def __init__(self, repository: TaskRepository) -> None:
        self._repository = repository

    async def execute(self, task_id: UUID) -> TaskLike:
        task = await self._repository.get(task_id)
        if task is None:
            raise LookupError("task not found")
        task.queue()
        await self._repository.save(task)
        return task


class RetryTask:
    def __init__(self, repository: TaskRepository, create: CreateTask) -> None:
        self._repository = repository
        self._create = create

    async def execute(self, task_id: UUID) -> TaskLike:
        task = await self._repository.get(task_id)
        if task is None:
            raise LookupError("task not found")
        task_type = getattr(task, "task_type")
        return await self._create.execute(task_type)


class ReconcileTasks:
    def __init__(self, repository: TaskRepository) -> None:
        self._repository = repository

    async def recover(self, task_id: UUID) -> TaskLike:
        task = await self._repository.get(task_id)
        if task is None:
            raise LookupError("task not found")
        task.recover()
        await self._repository.save(task)
        return task
