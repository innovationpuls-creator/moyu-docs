from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from dataclasses import dataclass
from decimal import Decimal
from uuid import uuid4

import pytest
from task_runtime.domain import RetryableTaskError, RetryPolicy
from task_runtime.registry import (
    HandlerRegistry,
    HandlerSpec,
    UnknownTaskTypeError,
    UnsupportedTaskVersionError,
)
from task_runtime.runtime import (
    CancellationRequested,
    HandlerContext,
    WorkerHost,
)


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
    failure_code: str | None = None


class Repo:
    def __init__(self) -> None:
        self.task = Task(uuid4())
        self.claim = Claim(self.task.task_id, uuid4(), 1)
        self.task.current_attempt_id = self.claim.attempt_id
        self.task.execution_epoch = self.claim.execution_epoch
        self.finished = False
        self.retried = False
        self.progress = []
        self.finish_calls: list[dict[str, object]] = []

    async def claim_next(self, worker_id, lease_seconds):
        return None if self.finished else self.claim

    async def get(self, task_id):
        return self.task

    async def heartbeat(self, *args):
        return True

    async def finish(self, *args, **kwargs):
        self.finished = True
        self.finish_calls.append(kwargs)
        self.task.failure_code = kwargs.get("failure_code")

    async def finish_cancelled(self, *args):
        self.finished = True

    async def update_progress(self, *args, **kwargs):
        self.progress.append((args, kwargs))

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
async def test_progress_is_fenced_and_uses_the_control_repository():
    control = Repo()
    execution = Repo()
    execution.task = control.task

    context = HandlerContext(
        control.task,
        control.claim.attempt_id,
        control.claim.execution_epoch,
        execution,
        control_repository=control,
    )
    await context.report_progress(
        stage="replaying",
        message_code="history.restore.replaying",
        current=1,
        total=3,
    )

    assert len(control.progress) == 1
    assert control.progress[0][1] == {
        "stage": "replaying",
        "message_code": "history.restore.replaying",
        "current": 1,
        "total": 3,
        "percentage": Decimal("33.33"),
    }
    assert execution.progress == []


@pytest.mark.asyncio
async def test_progress_checks_cancellation_before_persisting():
    repo = Repo()
    repo.task.cancel_requested_at = object()
    context = HandlerContext(
        repo.task, repo.claim.attempt_id, repo.claim.execution_epoch, repo
    )

    with pytest.raises(CancellationRequested):
        await context.report_progress(stage="replaying", current=0, total=0)

    assert repo.progress == []


@pytest.mark.asyncio
async def test_progress_checks_cancellation_after_persisting():
    class CancelAfterProgressRepo(Repo):
        async def update_progress(self, *args, **kwargs):
            await super().update_progress(*args, **kwargs)
            self.task.cancel_requested_at = object()

    repo = CancelAfterProgressRepo()
    context = HandlerContext(
        repo.task, repo.claim.attempt_id, repo.claim.execution_epoch, repo
    )

    with pytest.raises(CancellationRequested):
        await context.report_progress(stage="replaying", current=0, total=0)

    assert len(repo.progress) == 1


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
    assert repo.finish_calls == [{"failure_code": "TASK_EXECUTION_FAILED"}]
    assert repo.task.failure_code == "TASK_EXECUTION_FAILED"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("task_type", "schema_version", "failure_code"),
    [
        ("unknown", "1.0.0", "UNKNOWN_TASK_TYPE"),
        ("demo", "9.9.9", "UNSUPPORTED_TASK_VERSION"),
    ],
)
async def test_registry_failure_finishes_with_stable_failure_code(
    task_type: str, schema_version: str, failure_code: str
) -> None:
    repo = Repo()
    repo.task.task_type = task_type
    repo.task.schema_version = schema_version
    registry = HandlerRegistry()
    registry.register(HandlerSpec("demo", Handler()))
    worker = WorkerHost(repo, registry, worker_id="w", heartbeat_seconds=60)

    assert await worker.run_once()

    assert repo.finish_calls == [{"failure_code": failure_code}]
    assert repo.task.failure_code == failure_code


@pytest.mark.asyncio
async def test_exhausted_retry_finishes_with_handler_failure_code() -> None:
    repo = Repo()
    repo.claim.attempt_number = 2
    registry = HandlerRegistry()
    registry.register(
        HandlerSpec("demo", RetryHandler(), retry_policy=RetryPolicy(max_attempts=2))
    )
    worker = WorkerHost(repo, registry, worker_id="w", heartbeat_seconds=60)

    assert await worker.run_once()

    assert repo.finished
    assert not repo.retried
    assert repo.finish_calls == [{"failure_code": "temporary"}]
    assert repo.task.failure_code == "temporary"


@pytest.mark.asyncio
async def test_successful_retry_clears_previous_failure_code() -> None:
    repo = Repo()
    repo.task.failure_code = "previous-attempt-failure"
    registry = HandlerRegistry()
    registry.register(HandlerSpec("demo", Handler()))
    worker = WorkerHost(repo, registry, worker_id="w", heartbeat_seconds=60)

    assert await worker.run_once()

    assert repo.finished
    assert repo.finish_calls == [{"failure_code": None}]
    assert repo.task.failure_code is None


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


@pytest.mark.asyncio
async def test_scoped_success_commits_handler_and_finish_and_heartbeats_separately():
    events: list[str] = []

    class ControlRepo(Repo):
        async def heartbeat(self, *args):
            events.append("control.heartbeat")
            return True

    control = ControlRepo()

    class ScopedRepo(Repo):
        async def get(self, task_id):
            events.append("execution.get")
            return self.task

        async def finish(self, *args, **kwargs):
            events.append("execution.finish")
            self.finished = True

        async def heartbeat(self, *args):
            events.append("execution.heartbeat")
            return True

    execution_repo = ScopedRepo()
    execution_repo.task = control.task
    execution_repo.claim = control.claim

    class SlowHandler:
        async def execute(self, context):
            await context.checkpoint()
            await asyncio.sleep(0.01)

    registry = HandlerRegistry()
    registry.register(HandlerSpec("demo", SlowHandler()))

    @asynccontextmanager
    async def scope_factory():
        events.append("execution.begin")
        scope = WorkerExecutionScopeImpl(execution_repo, registry)
        try:
            yield scope
        except Exception:
            events.append("execution.rollback")
            raise
        else:
            events.append("execution.commit")

    worker = WorkerHost(
        control,
        HandlerRegistry(),
        worker_id="w",
        heartbeat_seconds=0.001,
        execution_scope_factory=scope_factory,
    )
    assert await worker.run_once()
    assert events.index("execution.finish") < events.index("execution.commit")
    assert "execution.rollback" not in events
    assert "execution.heartbeat" not in events
    assert "control.heartbeat" in events
    assert control.finished is False
    assert execution_repo.finished


@pytest.mark.asyncio
async def test_scoped_failure_rolls_back_before_retry_is_recorded():
    events: list[str] = []

    class ControlRepo(Repo):
        async def schedule_retry(self, *args):
            events.append("control.retry")
            self.retried = True

    control = ControlRepo()

    class ScopedRepo(Repo):
        async def get(self, task_id):
            events.append("execution.get")
            return self.task

    execution_repo = ScopedRepo()
    execution_repo.task = control.task
    execution_repo.claim = control.claim

    class RetryHandler:
        async def execute(self, context):
            await context.checkpoint()
            events.append("handler.side-effect")
            raise RetryableTaskError("temporary")

    registry = HandlerRegistry()
    registry.register(
        HandlerSpec("demo", RetryHandler(), retry_policy=RetryPolicy(max_attempts=2))
    )

    @asynccontextmanager
    async def scope_factory():
        events.append("execution.begin")
        try:
            yield WorkerExecutionScopeImpl(execution_repo, registry)
        except Exception:
            events.append("execution.rollback")
            raise
        else:
            events.append("execution.commit")

    worker = WorkerHost(
        control,
        HandlerRegistry(),
        worker_id="w",
        heartbeat_seconds=60,
        execution_scope_factory=scope_factory,
    )
    assert await worker.run_once()
    assert events.index("execution.rollback") < events.index("control.retry")
    assert "execution.commit" not in events
    assert control.retried


@pytest.mark.asyncio
async def test_scoped_fatal_failure_rolls_back_before_terminal_failure():
    events: list[str] = []

    class ControlRepo(Repo):
        async def finish(self, *args, **kwargs):
            events.append("control.finish")
            self.finish_calls.append(kwargs)
            self.finished = True

    control = ControlRepo()

    class ScopedRepo(Repo):
        async def get(self, task_id):
            return self.task

    execution_repo = ScopedRepo()
    execution_repo.task = control.task
    execution_repo.claim = control.claim

    class FatalHandler:
        async def execute(self, context):
            events.append("handler.side-effect")
            raise RuntimeError("fatal")

    registry = HandlerRegistry()
    registry.register(HandlerSpec("demo", FatalHandler()))

    @asynccontextmanager
    async def scope_factory():
        try:
            yield WorkerExecutionScopeImpl(execution_repo, registry)
        except Exception:
            events.append("execution.rollback")
            raise
        else:
            events.append("execution.commit")

    worker = WorkerHost(
        control,
        HandlerRegistry(),
        worker_id="w",
        heartbeat_seconds=60,
        execution_scope_factory=scope_factory,
    )
    assert await worker.run_once()
    assert events.index("execution.rollback") < events.index("control.finish")
    assert "execution.commit" not in events
    assert control.finished
    assert control.finish_calls == [{"failure_code": "TASK_EXECUTION_FAILED"}]


class WorkerExecutionScopeImpl:
    def __init__(self, repository, registry):
        self.repository = repository
        self.registry = registry
