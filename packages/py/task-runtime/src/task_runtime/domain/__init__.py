from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum


class RetryableTaskError(Exception):
    """A handler failure that may consume one bounded retry attempt."""

    def __init__(self, failure_code: str) -> None:
        super().__init__(failure_code)
        self.failure_code = failure_code


class AttemptState(StrEnum):
    RUNNING = "Running"
    SUCCEEDED = "Succeeded"
    FAILED = "Failed"
    CANCELLED = "Cancelled"


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
