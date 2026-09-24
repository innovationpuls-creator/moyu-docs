from __future__ import annotations

import logging
from dataclasses import dataclass
from uuid import uuid4

import pytest
from task_runtime.domain import RetryableTaskError, RetryPolicy
from task_runtime.registry import (
    HandlerRegistry,
    HandlerSpec,
    UnknownTaskTypeError,
    UnsupportedTaskVersionError,
)
from task_runtime.runtime import WorkerHost


@dataclass
class Claim:
    task_id: object
    attempt_id: object
    execution_epoch: int
    attempt_number: int = 1


@dataclass
class Task:
    task_id: object
    task_type: str = "demo"
    schema_version: str = "1.0.0"
    cancel_requested_at: object = None
    current_attempt_id: object = None
    execution_epoch: object = None


class Repo:
    def __init__(self) -> None:
        self.task = Task(uuid4())
        self.claim = Claim(self.task.task_id, uuid4(), 1)
        self.task.current_attempt_id = self.claim.attempt_id
        self.task.execution_epoch = self.claim.execution_epoch
        self.finished = False
        self.retried = False

    async def claim_next(self, worker_id, lease_seconds):
        return None if self.finished else self.claim

    async def get(self, task_id):
        return self.task

    async def heartbeat(self, *args):
        return True

    async def finish(self, *args):
        self.finished = True

    async def finish_cancelled(self, *args):
        self.finished = True

    async def schedule_retry(self, *args):
        self.retried = True


class Handler:
    async def execute(self, context):
        await context.checkpoint()


class RetryHandler:
    async def execute(self, context):
        raise RetryableTaskError("temporary")


class FatalHandler:
    async def execute(self, context):
        raise RuntimeError("fatal")


def test_registry_rejects_unknown_type_and_version():
    registry = HandlerRegistry()
    registry.register(HandlerSpec("demo", Handler()))
    with pytest.raises(UnknownTaskTypeError):
        registry.resolve("missing", "1.0.0")
    with pytest.raises(UnsupportedTaskVersionError):
        registry.resolve("demo", "2.0.0")


@pytest.mark.asyncio
async def test_worker_claims_executes_and_finishes():
    repo = Repo()
    registry = HandlerRegistry()
    registry.register(HandlerSpec("demo", Handler()))
    worker = WorkerHost(repo, registry, worker_id="w", heartbeat_seconds=60)
    assert await worker.run_once()
    assert repo.finished


@pytest.mark.asyncio
@pytest.mark.asyncio
async def test_retryable_failure_uses_retry_budget():
    repo = Repo()
    registry = HandlerRegistry()
    registry.register(
        HandlerSpec("demo", RetryHandler(), retry_policy=RetryPolicy(max_attempts=2))
    )
    worker = WorkerHost(repo, registry, worker_id="w", heartbeat_seconds=60)
    assert await worker.run_once()
    assert repo.retried
    assert not repo.finished


@pytest.mark.asyncio
async def test_fatal_failure_finishes_failed():
    repo = Repo()
    registry = HandlerRegistry()
    registry.register(HandlerSpec("demo", FatalHandler()))
    worker = WorkerHost(repo, registry, worker_id="w", heartbeat_seconds=60)
    assert await worker.run_once()
    assert repo.finished


@pytest.mark.asyncio
async def test_cancellation_checkpoint_closes_cancelled():
    repo = Repo()
    repo.task.cancel_requested_at = object()
    registry = HandlerRegistry()
    registry.register(HandlerSpec("demo", Handler()))
    worker = WorkerHost(repo, registry, worker_id="w", heartbeat_seconds=60)
    assert await worker.run_once()
    assert repo.finished


@pytest.mark.asyncio
async def test_execution_record_logged_with_task_correlation() -> None:
    """Arch 23: the runtime emits a structured execution record per run_once."""
    records: list[logging.LogRecord] = []
    handler = logging.Handler()
    handler.emit = lambda record: records.append(record)  # type: ignore[method-assign]
    execution = logging.getLogger("dom.worker.execution")
    execution.addHandler(handler)
    execution.setLevel(logging.INFO)
    execution.propagate = False
    try:
        repo = Repo()
        registry = HandlerRegistry()
        registry.register(HandlerSpec("demo", Handler()))
        worker = WorkerHost(repo, registry, worker_id="w", heartbeat_seconds=60)
        executed = await worker.run_once()
        assert executed is True
        record = records[-1]
        assert record.name == "dom.worker.execution"
        assert record.result == "ok"
        assert record.taskId == str(repo.task.task_id)
        assert record.workerId == "w"
        assert record.duration_ms >= 0
    finally:
        execution.removeHandler(handler)
