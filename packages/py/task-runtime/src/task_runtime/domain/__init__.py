from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Mapping, cast
from uuid import UUID, uuid4


class TaskTransitionError(ValueError):
    """Raised when a generic task transition is not legal."""


class StaleAttemptError(RuntimeError):
    """Raised when an attempt no longer owns task execution."""


class RetryableTaskError(Exception):
    """A handler failure that may consume one bounded retry attempt."""

    def __init__(self, failure_code: str) -> None:
        super().__init__(failure_code)
        self.failure_code = failure_code


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


class AttemptState(StrEnum):
    RUNNING = "Running"
    SUCCEEDED = "Succeeded"
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


@dataclass(frozen=True)
class RetryPolicy:
    max_attempts: int = 3
    backoff_seconds: int = 1

    def __post_init__(self) -> None:
        if self.max_attempts < 1:
            raise ValueError("max_attempts must be positive")
        if self.backoff_seconds < 0:
            raise ValueError("backoff_seconds must not be negative")

    def can_retry(self, attempt_number: int) -> bool:
        """Allow retries while the one-based attempt is below max_attempts."""
        return 0 < attempt_number < self.max_attempts


@dataclass(frozen=True)
class Lease:
    worker_id: str
    execution_epoch: int
    lease_until: float

    def is_valid(self, *, worker_id: str, execution_epoch: int, now: float) -> bool:
        return (
            self.worker_id == worker_id
            and self.execution_epoch == execution_epoch
            and now < self.lease_until
        )


@dataclass
class CancelRequested:
    requested_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    completed: bool = False

    def complete(self) -> None:
        self.completed = True


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
    queued_at: datetime | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    failure_code: str | None = None
    current_attempt_id: UUID | None = None
    execution_epoch: int = 0

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
            queued_at=cast(datetime | None, value["queued_at"]),
            started_at=cast(datetime | None, value["started_at"]),
            finished_at=cast(datetime | None, value["finished_at"]),
            failure_code=cast(str | None, value["failure_code"]),
            current_attempt_id=cast(UUID | None, value["current_attempt_id"]),
            execution_epoch=cast(int, value.get("execution_epoch") or 0),
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
