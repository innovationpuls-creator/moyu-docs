from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Callable
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from typing import Any, AsyncContextManager, Protocol
from uuid import UUID

from app_core.operations.task.domain import StaleAttemptError
from opentelemetry import trace

from task_runtime.domain import RetryableTaskError
from task_runtime.registry import (
    HandlerRegistry,
    UnknownTaskTypeError,
    UnsupportedTaskVersionError,
)

UNKNOWN_TASK_TYPE_FAILURE_CODE = "UNKNOWN_TASK_TYPE"
UNSUPPORTED_TASK_VERSION_FAILURE_CODE = "UNSUPPORTED_TASK_VERSION"
TASK_EXECUTION_FAILURE_CODE = "TASK_EXECUTION_FAILED"


class TaskRuntimeRepository(Protocol):
    async def claim_next(self, worker_id: str, lease_seconds: int) -> Any | None: ...
    async def get(self, task_id: UUID) -> Any | None: ...
    async def heartbeat(
        self, task_id: UUID, attempt_id: UUID, epoch: int, lease_seconds: int
    ) -> bool: ...
    async def finish(
        self,
        task_id: UUID,
        attempt_id: UUID,
        epoch: int,
        succeeded: bool,
        *,
        failure_code: str | None = None,
    ) -> None: ...
    async def finish_cancelled(
        self, task_id: UUID, attempt_id: UUID, epoch: int
    ) -> None: ...
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
    async def schedule_retry(
        self, task_id: UUID, next_attempt_at: Any, failure_code: str
    ) -> None: ...

    async def find_expired_leases(self, now: Any) -> list[UUID]: ...

    async def release_for_recovery(
        self, task_id: UUID, attempt_id: UUID, epoch: int
    ) -> None: ...


class RuntimeTracer(Protocol):
    def start_as_current_span(self, name: str, **kwargs: Any) -> Any: ...


class WorkerExecutionScope(Protocol):
    """Repositories and handlers bound to one caller-owned execution unit."""

    repository: TaskRuntimeRepository
    registry: HandlerRegistry


class CancellationRequested(Exception):
    pass


@dataclass
class HandlerContext:
    task: Any
    attempt_id: UUID
    execution_epoch: int
    repository: TaskRuntimeRepository
    control_repository: TaskRuntimeRepository | None = None

    async def checkpoint(self) -> None:
        repository = self.control_repository or self.repository
        current = await repository.get(self.task.task_id)
        if current is None:
            raise StaleAttemptError("task no longer exists")
        if (
            getattr(current, "current_attempt_id", None) != self.attempt_id
            or getattr(current, "execution_epoch", None) != self.execution_epoch
        ):
            raise StaleAttemptError("attempt is no longer authoritative")
        if current.cancel_requested_at is not None:
            raise CancellationRequested

    async def report_progress(
        self,
        *,
        stage: str | None = None,
        message_code: str | None = None,
        current: int | None = None,
        total: int | None = None,
    ) -> None:
        """Persist a fenced progress snapshot at a cooperative cancel point."""
        if current is not None and current < 0:
            raise ValueError("progress current must not be negative")
        if total is not None and total < 0:
            raise ValueError("progress total must not be negative")
        if current is not None and total is not None and current > total:
            raise ValueError("progress current must not exceed total")

        await self.checkpoint()
        percentage = None
        if current is not None and total is not None and total > 0:
            percentage = (Decimal(current * 100) / Decimal(total)).quantize(
                Decimal("0.01"), rounding=ROUND_HALF_UP
            )
        repository = self.control_repository or self.repository
        await repository.update_progress(
            self.task.task_id,
            self.attempt_id,
            self.execution_epoch,
            stage=stage,
            message_code=message_code,
            current=current,
            total=total,
            percentage=percentage,
        )
        await self.checkpoint()


class WorkerHost:
    def __init__(
        self,
        repository: TaskRuntimeRepository,
        registry: HandlerRegistry,
        *,
        worker_id: str,
        lease_seconds: int = 30,
        heartbeat_seconds: float = 10.0,
        tracer: RuntimeTracer | None = None,
        execution_scope_factory: (
            Callable[[], AsyncContextManager[WorkerExecutionScope]] | None
        ) = None,
    ) -> None:
        self.repository = repository
        self.registry = registry
        self.worker_id = worker_id
        self.lease_seconds = lease_seconds
        self.heartbeat_seconds = heartbeat_seconds
        self.tracer = tracer or trace.get_tracer("task-runtime")
        self.execution_scope_factory = execution_scope_factory
        self._stopping = False
        self._active = 0
        self._execution_logger = logging.getLogger("dom.worker.execution")

    async def run_once(self) -> bool:
        claim = await self.repository.claim_next(self.worker_id, self.lease_seconds)
        if claim is None:
            return False
        self._active += 1
        started = time.monotonic()
        try:
            task, result = await self._execute_claim(claim)
        finally:
            self._active -= 1
        if task is not None:
            self._log_execution(task, result, claim, started)
        return True

    async def _execute_claim(self, claim: Any) -> tuple[Any | None, str]:
        task = None
        spec = None
        try:
            if self.execution_scope_factory is None:
                repository = self.repository
                registry = self.registry
                task = await repository.get(claim.task_id)
                if task is not None:
                    spec = registry.resolve(task.task_type, task.schema_version)
                    await self._execute_handler_and_finish(
                        claim, repository, task, spec
                    )
            else:
                async with self.execution_scope_factory() as scope:
                    repository = scope.repository
                    task = await repository.get(claim.task_id)
                    if task is not None:
                        spec = scope.registry.resolve(
                            task.task_type, task.schema_version
                        )
                        await self._execute_handler_and_finish(
                            claim, repository, task, spec
                        )
            return task, "ok" if task is not None else "missing-task"
        except Exception as exc:
            return task, await self._record_execution_failure(claim, spec, exc)

    async def _record_execution_failure(
        self, claim: Any, spec: Any | None, error: Exception
    ) -> str:
        if isinstance(error, UnknownTaskTypeError):
            await self.repository.finish(
                claim.task_id,
                claim.attempt_id,
                claim.execution_epoch,
                False,
                failure_code=UNKNOWN_TASK_TYPE_FAILURE_CODE,
            )
            return "unknown-type"
        if isinstance(error, UnsupportedTaskVersionError):
            await self.repository.finish(
                claim.task_id,
                claim.attempt_id,
                claim.execution_epoch,
                False,
                failure_code=UNSUPPORTED_TASK_VERSION_FAILURE_CODE,
            )
            return "unsupported-version"
        if isinstance(error, CancellationRequested):
            await self.repository.finish_cancelled(
                claim.task_id, claim.attempt_id, claim.execution_epoch
            )
            return "cancelled"
        if isinstance(error, RetryableTaskError):
            if spec is not None and spec.retry_policy.can_retry(claim.attempt_number):
                from datetime import UTC, datetime, timedelta

                await self.repository.schedule_retry(
                    claim.task_id,
                    datetime.now(UTC)
                    + timedelta(seconds=spec.retry_policy.backoff_seconds),
                    error.failure_code,
                )
                return "retry"
            await self.repository.finish(
                claim.task_id,
                claim.attempt_id,
                claim.execution_epoch,
                False,
                failure_code=error.failure_code,
            )
            return "failed"
        await self.repository.finish(
            claim.task_id,
            claim.attempt_id,
            claim.execution_epoch,
            False,
            failure_code=TASK_EXECUTION_FAILURE_CODE,
        )
        return "failed"

    async def _execute_handler_and_finish(
        self, claim: Any, repository: TaskRuntimeRepository, task: Any, spec: Any
    ) -> None:
        context = HandlerContext(
            task,
            claim.attempt_id,
            claim.execution_epoch,
            repository,
            control_repository=self.repository,
        )
        heartbeat = asyncio.create_task(self._heartbeat(task.task_id, claim))
        try:
            with self.tracer.start_as_current_span("task.execute") as span:
                span.set_attribute("taskId", str(task.task_id))
                await spec.handler.execute(context)
            # In a scoped runner, handler writes and the terminal success update
            # share the caller-owned transaction and commit atomically.
            await repository.finish(
                task.task_id,
                claim.attempt_id,
                claim.execution_epoch,
                True,
                failure_code=None,
            )
        finally:
            heartbeat.cancel()
            await asyncio.gather(heartbeat, return_exceptions=True)

    def _log_execution(
        self, task: Any, result: str, claim: Any, started: float
    ) -> None:
        """Structured execution record (arch 23): taskId/type/attempt + outcome."""
        self._execution_logger.info(
            "task.execution",
            extra={
                "result": result,
                "duration_ms": round((time.monotonic() - started) * 1000, 2),
                "taskId": str(task.task_id),
                "taskType": getattr(task, "task_type", None),
                "attemptNumber": getattr(claim, "attempt_number", None),
                "workerId": self.worker_id,
            },
        )

    async def _heartbeat(self, task_id: UUID, claim: Any) -> None:
        while True:
            await asyncio.sleep(self.heartbeat_seconds)
            await self.repository.heartbeat(
                task_id, claim.attempt_id, claim.execution_epoch, self.lease_seconds
            )

    async def drain(self) -> None:
        self._stopping = True
        while self._active:
            await asyncio.sleep(0)

    async def run(self) -> None:
        while not self._stopping:
            if not await self.run_once():
                await asyncio.sleep(0)


class LeaseReconciler:
    """Requeue tasks whose current attempt lease has expired."""

    def __init__(self, repository: TaskRuntimeRepository) -> None:
        self.repository = repository

    async def reconcile(self, now: Any) -> list[UUID]:
        expired = await self.repository.find_expired_leases(now)
        requeued: list[UUID] = []
        for task_id in expired:
            task = await self.repository.get(task_id)
            if task is None or getattr(task, "state", None) != "Running":
                continue
            attempt_id = getattr(task, "current_attempt_id", None)
            epoch = getattr(task, "execution_epoch", None)
            if attempt_id is None or epoch is None:
                continue
            await self.repository.release_for_recovery(task_id, attempt_id, epoch)
            requeued.append(task_id)
        return requeued
