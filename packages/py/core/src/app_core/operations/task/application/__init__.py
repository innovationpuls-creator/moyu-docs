from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal
from typing import cast
from uuid import UUID

from app_core.common.exceptions import ConflictError, NotFoundError, ValidationError
from app_core.operations.task.domain import Priority, StaleAttemptError, Task
from app_core.operations.task.ports import (
    TaskLike,
    TaskRepository,
)


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
        actor_account_id: UUID | None = None,
        workspace_id: UUID | None = None,
        resource_id: UUID | None = None,
        retry_of_task_id: UUID | None = None,
        priority: Priority | None = None,
        idempotency_key: UUID | None = None,
    ) -> TaskLike:
        if idempotency_key is not None and actor_account_id is None:
            raise ValueError("idempotent tasks require an actor account")
        if self._task_factory is None:
            task = cast(TaskLike, Task.create(task_type))
            if task_id is not None:
                task.task_id = task_id
        else:
            task = cast(TaskLike, self._task_factory(task_type))
        for name, value in (
            ("input_ref", input_ref),
            ("actor_account_id", actor_account_id),
            ("workspace_id", workspace_id),
            ("resource_id", resource_id),
            ("retry_of_task_id", retry_of_task_id),
            ("idempotency_key", idempotency_key),
            ("progress_message_code", None),
            ("progress_current", None),
            ("progress_total", None),
            ("progress_percentage", None),
            ("progress_updated_at", None),
        ):
            setattr(task, name, value)
        if priority is not None:
            setattr(task, "priority", priority)
        task.queue()
        if idempotency_key is not None:
            idempotent = await self._repository.create_idempotent(task)
            if idempotent is None:
                raise RuntimeError("idempotent task insert returned no row")
            return idempotent
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


class UpdateTaskProgress:
    """Persist one progress snapshot under the current attempt fence.

    A missing stage or message code means keep the current label. Counter
    fields are replaced as a snapshot, so ``None`` clears unknown counters.
    """

    def __init__(self, repository: TaskRepository) -> None:
        self._repository = repository

    async def execute(
        self,
        task_id: UUID,
        attempt_id: UUID,
        execution_epoch: int,
        *,
        stage: str | None = None,
        message_code: str | None = None,
        current: int | None = None,
        total: int | None = None,
    ) -> None:
        if current is not None and current < 0:
            raise ValueError("progress current must not be negative")
        if total is not None and total < 0:
            raise ValueError("progress total must not be negative")
        if current is not None and total is not None and current > total:
            raise ValueError("progress current must not exceed total")

        percentage = None
        if current is not None and total is not None and total > 0:
            percentage = (Decimal(current * 100) / Decimal(total)).quantize(
                Decimal("0.01"), rounding=ROUND_HALF_UP
            )
        await self._repository.update_progress(
            task_id,
            attempt_id,
            execution_epoch,
            stage=stage,
            message_code=message_code,
            current=current,
            total=total,
            percentage=percentage,
        )


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

    async def execute(self, task_id: UUID, actor_account_id: UUID) -> TaskLike:
        task = await _get_owned_task(self._repository, task_id, actor_account_id)
        state = _state_value(task)
        if state in {"Succeeded", "PartialSucceeded", "Failed", "Cancelled"}:
            raise ConflictError(
                "A completed task cannot be cancelled.", "TASK_NOT_CANCELLABLE"
            )
        if getattr(task, "cancel_requested_at", None) is not None:
            return task

        await self._repository.request_cancel(task_id, datetime.now(UTC))
        updated = await _get_owned_task(self._repository, task_id, actor_account_id)
        if getattr(updated, "cancel_requested_at", None) is None:
            raise ConflictError(
                "Task cancellation was not accepted.", "TASK_CANCEL_NOT_ACCEPTED"
            )
        return updated


class ListTasks:
    def __init__(self, repository: TaskRepository) -> None:
        self._repository = repository

    async def execute(
        self, actor_account_id: UUID, *, limit: int = 50, offset: int = 0
    ) -> list[TaskLike]:
        if limit < 1 or limit > 100:
            raise ValidationError(
                "limit must be between 1 and 100.",
                "TASK_PAGINATION_INVALID",
                "limit",
            )
        if offset < 0:
            raise ValidationError(
                "offset must not be negative.",
                "TASK_PAGINATION_INVALID",
                "offset",
            )
        return await self._repository.list_for_actor(
            actor_account_id, limit=limit, offset=offset
        )


class GetTask:
    def __init__(self, repository: TaskRepository) -> None:
        self._repository = repository

    async def execute(self, task_id: UUID, actor_account_id: UUID) -> TaskLike:
        return await _get_owned_task(self._repository, task_id, actor_account_id)


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

    async def execute(
        self,
        task_id: UUID,
        actor_account_id: UUID,
        idempotency_key: UUID,
    ) -> TaskLike:
        existing = await self._repository.get_by_actor_idempotency_key(
            actor_account_id, idempotency_key
        )
        if existing is not None:
            if getattr(existing, "retry_of_task_id", None) != task_id:
                raise ConflictError(
                    "Idempotency key was used for another source task.",
                    "IDEMPOTENCY_KEY_CONFLICT",
                )
            return existing

        task = await _get_owned_task(self._repository, task_id, actor_account_id)
        if _state_value(task) != "Failed":
            raise ConflictError(
                "Only failed tasks can be retried.", "TASK_NOT_RETRYABLE"
            )
        retry = await self._create.execute(
            task.task_type,
            input_ref=getattr(task, "input_ref", None),
            actor_account_id=actor_account_id,
            workspace_id=getattr(task, "workspace_id", None),
            resource_id=getattr(task, "resource_id", None),
            retry_of_task_id=task.task_id,
            priority=getattr(task, "priority", None),
            idempotency_key=idempotency_key,
        )
        if getattr(retry, "retry_of_task_id", None) != task.task_id:
            raise ConflictError(
                "Idempotency key was used for another source task.",
                "IDEMPOTENCY_KEY_CONFLICT",
            )
        return retry


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


async def _get_owned_task(
    repository: TaskRepository, task_id: UUID, actor_account_id: UUID
) -> TaskLike:
    task = await repository.get(task_id)
    if task is None or getattr(task, "actor_account_id", None) != actor_account_id:
        raise NotFoundError("Task not found.", "TASK_NOT_FOUND")
    return task


def _state_value(task: TaskLike) -> str:
    state = getattr(task, "state", None)
    return str(getattr(state, "value", state))
