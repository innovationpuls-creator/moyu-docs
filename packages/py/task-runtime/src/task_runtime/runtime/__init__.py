from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass
from typing import Any, Protocol
from uuid import UUID

from opentelemetry import trace

from task_runtime.domain import (
    RetryableTaskError,
    StaleAttemptError,
)
from task_runtime.registry import (
    HandlerRegistry,
    UnknownTaskTypeError,
    UnsupportedTaskVersionError,
)


class TaskRuntimeRepository(Protocol):
    async def claim_next(self, worker_id: str, lease_seconds: int) -> Any | None: ...
    async def get(self, task_id: UUID) -> Any | None: ...
    async def heartbeat(
        self, task_id: UUID, attempt_id: UUID, epoch: int, lease_seconds: int
    ) -> bool: ...
    async def finish(
        self, task_id: UUID, attempt_id: UUID, epoch: int, succeeded: bool
    ) -> None: ...
    async def finish_cancelled(
        self, task_id: UUID, attempt_id: UUID, epoch: int
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


class CancellationRequested(Exception):
    pass


@dataclass
class HandlerContext:
    task: Any
    attempt_id: UUID
    execution_epoch: int
    repository: TaskRuntimeRepository

    async def checkpoint(self) -> None:
        current = await self.repository.get(self.task.task_id)
        if current is None:
            raise StaleAttemptError("task no longer exists")
        if (
            getattr(current, "current_attempt_id", None) != self.attempt_id
            or getattr(current, "execution_epoch", None) != self.execution_epoch
        ):
            raise StaleAttemptError("attempt is no longer authoritative")
        if current.cancel_requested_at is not None:
            raise CancellationRequested


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
    ) -> None:
        self.repository = repository
        self.registry = registry
        self.worker_id = worker_id
        self.lease_seconds = lease_seconds
        self.heartbeat_seconds = heartbeat_seconds
        self.tracer = tracer or trace.get_tracer("task-runtime")
        self._stopping = False
        self._active = 0
        self._execution_logger = logging.getLogger("dom.worker.execution")

    async def run_once(self) -> bool:
        claim = await self.repository.claim_next(self.worker_id, self.lease_seconds)
        if claim is None:
            return False
        self._active += 1
        task = await self.repository.get(claim.task_id)
        if task is None:
            self._active -= 1
            return False
        started = time.monotonic()
        try:
            try:
                spec = self.registry.resolve(task.task_type, task.schema_version)
            except UnknownTaskTypeError:
                task.failure_code = "unknown-type"
                await self.repository.finish(
                    task.task_id, claim.attempt_id, claim.execution_epoch, False
                )
                return True
            except UnsupportedTaskVersionError:
                task.failure_code = "unsupported-version"
                await self.repository.finish(
                    task.task_id, claim.attempt_id, claim.execution_epoch, False
                )
                return True
            context = HandlerContext(
                task, claim.attempt_id, claim.execution_epoch, self.repository
            )
            heartbeat = asyncio.create_task(self._heartbeat(task.task_id, claim))
            try:
                with self.tracer.start_as_current_span("task.execute") as span:
                    span.set_attribute("taskId", str(task.task_id))
                    await spec.handler.execute(context)
                await self.repository.finish(
                    task.task_id, claim.attempt_id, claim.execution_epoch, True
                )
                result = "ok"
            except CancellationRequested:
                await self.repository.finish_cancelled(
                    task.task_id, claim.attempt_id, claim.execution_epoch
                )
                result = "cancelled"
            except RetryableTaskError as exc:
                if spec.retry_policy.can_retry(claim.attempt_number):
                    from datetime import UTC, datetime, timedelta

                    await self.repository.schedule_retry(
                        task.task_id,
                        datetime.now(UTC)
                        + timedelta(seconds=spec.retry_policy.backoff_seconds),
                        exc.failure_code,
                    )
                else:
                    task.failure_code = exc.failure_code
                    await self.repository.finish(
                        task.task_id, claim.attempt_id, claim.execution_epoch, False
                    )
                result = (
                    "retry"
                    if spec.retry_policy.can_retry(claim.attempt_number)
                    else "failed"
                )
            except Exception:
                task.failure_code = "handler-failed"
                await self.repository.finish(
                    task.task_id, claim.attempt_id, claim.execution_epoch, False
                )
                result = "failed"
            finally:
                heartbeat.cancel()
                await asyncio.gather(heartbeat, return_exceptions=True)
        finally:
            self._active -= 1
        self._log_execution(task, result, claim, started)
        return True

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
