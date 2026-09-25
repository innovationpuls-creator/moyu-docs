from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from enum import StrEnum
from typing import cast
from uuid import UUID, uuid4


class TaskTransitionError(ValueError):
    """Raised when a Task lifecycle transition is not legal."""


class StaleAttemptError(RuntimeError):
    """Raised when an execution attempt no longer owns a Task."""


class TaskState(StrEnum):
    CREATED = "Created"
    QUEUED = "Queued"
    RUNNING = "Running"
    WAITING_FOR_USER = "WaitingForUser"
    RETRYING = "Retrying"
    SUCCEEDED = "Succeeded"
    PARTIAL_SUCCEEDED = "PartialSucceeded"
    FAILED = "Failed"
    CANCELLED = "Cancelled"


class Priority(StrEnum):
    INTERACTIVE = "Interactive"
    NORMAL = "Normal"
    BACKGROUND = "Background"
    MAINTENANCE = "Maintenance"


TERMINAL_STATES = frozenset(
    {
        TaskState.SUCCEEDED,
        TaskState.PARTIAL_SUCCEEDED,
        TaskState.FAILED,
        TaskState.CANCELLED,
    }
)


@dataclass
class Task:
    task_id: UUID
    task_type: str
    priority: Priority
    state: TaskState = TaskState.CREATED
    retry_count: int = 0
    cancel_requested_at: datetime | None = None
    schema_version: str = "1.0.0"
    stage: str | None = None
    actor_account_id: UUID | None = None
    workspace_id: UUID | None = None
    resource_id: UUID | None = None
    input_ref: str | None = None
    result_ref: str | None = None
    retry_of_task_id: UUID | None = None
    idempotency_key: UUID | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
    queued_at: datetime | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    next_attempt_at: datetime | None = None
    failure_code: str | None = None
    current_attempt_id: UUID | None = None
    execution_epoch: int = 0
    progress_message_code: str | None = None
    progress_current: int | None = None
    progress_total: int | None = None
    progress_percentage: Decimal | None = None
    progress_updated_at: datetime | None = None

    @classmethod
    def create(cls, task_type: str, *, priority: Priority = Priority.NORMAL) -> Task:
        if not task_type:
            raise ValueError("task_type must not be empty")
        return cls(uuid4(), task_type, priority)

    @classmethod
    def from_row(cls, row: Mapping[str, object]) -> Task:
        value = cast(dict[str, object], dict(row))
        return cls(
            task_id=cast(UUID, value["task_id"]),
            task_type=cast(str, value["task_type"]),
            priority=Priority(cast(str, value["priority"])),
            state=TaskState(cast(str, value["state"])),
            retry_count=cast(int, value["retry_count"] or 0),
            cancel_requested_at=cast(datetime | None, value["cancel_requested_at"]),
            schema_version=cast(str, value["schema_version"]),
            stage=cast(str | None, value["stage"]),
            actor_account_id=cast(UUID | None, value["actor_account_id"]),
            workspace_id=cast(UUID | None, value["workspace_id"]),
            resource_id=cast(UUID | None, value["resource_id"]),
            input_ref=cast(str | None, value["input_ref"]),
            result_ref=cast(str | None, value["result_ref"]),
            retry_of_task_id=cast(UUID | None, value["retry_of_task_id"]),
            idempotency_key=cast(UUID | None, value.get("idempotency_key")),
            created_at=cast(datetime | None, value.get("created_at")),
            updated_at=cast(datetime | None, value.get("updated_at")),
            queued_at=cast(datetime | None, value["queued_at"]),
            started_at=cast(datetime | None, value["started_at"]),
            finished_at=cast(datetime | None, value["finished_at"]),
            next_attempt_at=cast(datetime | None, value.get("next_attempt_at")),
            failure_code=cast(str | None, value["failure_code"]),
            current_attempt_id=cast(UUID | None, value["current_attempt_id"]),
            execution_epoch=cast(int, value.get("execution_epoch") or 0),
            progress_message_code=cast(str | None, value.get("progress_message_code")),
            progress_current=cast(int | None, value.get("progress_current")),
            progress_total=cast(int | None, value.get("progress_total")),
            progress_percentage=cast(Decimal | None, value.get("progress_percentage")),
            progress_updated_at=cast(datetime | None, value.get("progress_updated_at")),
        )

    def _transition(self, *allowed: TaskState, target: TaskState) -> None:
        if self.state not in allowed:
            raise TaskTransitionError(
                f"cannot transition {self.state.value} to {target.value}"
            )
        self.state = target

    def queue(self) -> None:
        self._transition(
            TaskState.CREATED,
            TaskState.RETRYING,
            TaskState.WAITING_FOR_USER,
            target=TaskState.QUEUED,
        )

    def recover(self) -> None:
        """Requeue after lease expiry/reconciliation (caller verified staleness)."""
        self._transition(TaskState.RUNNING, target=TaskState.QUEUED)

    def start(self) -> None:
        self._transition(TaskState.QUEUED, target=TaskState.RUNNING)

    def wait_for_user(self) -> None:
        self._transition(TaskState.RUNNING, target=TaskState.WAITING_FOR_USER)

    def retry(self) -> None:
        self._transition(TaskState.RUNNING, target=TaskState.RETRYING)
        self.retry_count += 1

    def succeed(self, *, partial: bool = False) -> None:
        self._transition(
            TaskState.RUNNING,
            TaskState.WAITING_FOR_USER,
            target=(TaskState.PARTIAL_SUCCEEDED if partial else TaskState.SUCCEEDED),
        )

    def fail(self) -> None:
        self._transition(
            TaskState.RUNNING,
            TaskState.RETRYING,
            TaskState.WAITING_FOR_USER,
            target=TaskState.FAILED,
        )

    def cancel(self) -> None:
        self._transition(
            TaskState.CREATED,
            TaskState.QUEUED,
            TaskState.WAITING_FOR_USER,
            TaskState.RUNNING,
            TaskState.RETRYING,
            target=TaskState.CANCELLED,
        )
        self.cancel_requested_at = self.cancel_requested_at or datetime.now(UTC)
