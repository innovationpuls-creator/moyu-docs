from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Protocol
from uuid import UUID

from app_core.operations.task.domain import Priority, TaskState


class TaskLike(Protocol):
    task_id: UUID
    task_type: str
    priority: Priority
    state: TaskState
    stage: str | None
    actor_account_id: UUID | None
    workspace_id: UUID | None
    resource_id: UUID | None
    input_ref: str | None
    result_ref: str | None
    retry_of_task_id: UUID | None
    idempotency_key: UUID | None
    retry_count: int
    cancel_requested_at: datetime | None
    queued_at: datetime | None
    started_at: datetime | None
    finished_at: datetime | None
    failure_code: str | None
    progress_message_code: str | None
    progress_current: int | None
    progress_total: int | None
    progress_percentage: Decimal | None
    progress_updated_at: datetime | None

    def queue(self) -> None: ...

    def recover(self) -> None: ...

    def succeed(self) -> None: ...

    def fail(self) -> None: ...


class TaskRepository(Protocol):
    async def create(self, task: TaskLike) -> bool: ...

    async def get(self, task_id: UUID) -> TaskLike | None: ...

    async def get_by_actor_idempotency_key(
        self, actor_account_id: UUID, idempotency_key: UUID
    ) -> TaskLike | None: ...

    async def create_idempotent(self, task: TaskLike) -> TaskLike | None: ...

    async def list_for_actor(
        self, actor_account_id: UUID, *, limit: int, offset: int
    ) -> list[TaskLike]: ...

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

    async def update_progress(
        self,
        task_id: UUID,
        attempt_id: UUID,
        execution_epoch: int,
        *,
        stage: str | None,
        message_code: str | None,
        current: int | None,
        total: int | None,
        percentage: Decimal | None,
    ) -> None: ...


class TaskEventPublisher(Protocol):
    async def publish(self, event_type: str, task: TaskLike) -> None: ...
