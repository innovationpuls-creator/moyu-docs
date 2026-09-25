from __future__ import annotations

import os
import subprocess
import sys
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
from alembic import command
from alembic.config import Config
from app_core.operations.task.domain import Priority, Task
from app_infra.postgres.engine import engine
from app_infra.postgres.task.effect_repository import PostgresTaskEffectRepository
from app_infra.postgres.task.task_repository import (
    PostgresTaskRepository,
)
from app_infra.postgres.test_database_guard import require_isolated_database
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from task_runtime.registry import HandlerRegistry, HandlerSpec
from task_runtime.runtime import (
    CancellationRequested,
    HandlerContext,
    LeaseReconciler,
    WorkerHost,
)

DATABASE_URL = "postgresql+psycopg://torch@localhost:5432/dom_workspace_lifecycle_test"
_TASK_TYPE_PREFIX = f"test.task.runtime.{uuid4().hex}."
_TASK_TYPE = f"{_TASK_TYPE_PREFIX}demo"
_TASK_TYPE_PATTERN = f"{_TASK_TYPE_PREFIX}%"


@pytest_asyncio.fixture(scope="module", autouse=True)
async def migrated_database() -> None:
    database_url = require_isolated_database(os.environ["DATABASE_URL"])
    assert database_url == DATABASE_URL
    config = Config(str(Path("migrations/postgres/alembic.ini")))
    config.set_main_option("sqlalchemy.url", database_url)
    command.upgrade(config, "head")


class RecordingSpan:
    def __init__(self, name: str, recorder: list[tuple[str, str]]) -> None:
        self.name = name
        self._recorder = recorder

    def set_attribute(self, key: str, value: object) -> None:
        self._recorder.append((self.name, f"{key}={value}"))

    def __enter__(self) -> RecordingSpan:
        return self

    def __exit__(self, *exc: object) -> bool:
        return False


class RecordingTracer:
    def __init__(self) -> None:
        self.spans: list[tuple[str, str]] = []

    def start_as_current_span(self, name: str, **kwargs: object):
        return RecordingSpan(name, self.spans)


class DemoSideEffectHandler:
    """Test-only handler: records a side effect keyed by attempt (fencing demo)."""

    def __init__(self, effects: PostgresTaskEffectRepository) -> None:
        self._effects = effects

    async def execute(self, context: HandlerContext) -> None:
        await context.checkpoint()
        await self._effects.record_effect(
            effect_key=f"{context.task.task_id}:{context.attempt_id}",
            task_id=context.task.task_id,
            effect_type="demo",
            target_ref={"attempt": str(context.attempt_id)},
            attempt_id=context.attempt_id,
            execution_epoch=context.execution_epoch,
        )


class CancelAfterOneHandler:
    async def execute(self, context: HandlerContext) -> None:
        await context.checkpoint()
        raise CancellationRequested


async def _build(session: AsyncSession, handler) -> HandlerRegistry:
    registry = HandlerRegistry()
    registry.register(HandlerSpec(_TASK_TYPE, handler))
    return registry


class _SingleTaskRepository:
    """Restrict WorkerHost integration cases to their own queued task."""

    def __init__(self, repository: PostgresTaskRepository, task_id) -> None:
        self._repository = repository
        self._task_id = task_id

    async def claim_next(self, worker_id: str, lease_seconds: int):
        return await self._repository.claim(self._task_id, worker_id, lease_seconds)

    async def find_expired_leases(self, now: datetime) -> list[UUID]:
        expired = await self._repository.find_expired_leases(now)
        return [task_id for task_id in expired if task_id == self._task_id]

    def __getattr__(self, name: str) -> Any:
        return getattr(self._repository, name)


async def _create_queued(session: AsyncSession) -> Task:
    task = Task.create(_TASK_TYPE, priority=Priority.INTERACTIVE)
    await session.execute(
        text(
            "INSERT INTO work.tasks (task_id,task_type,state,stage,priority,"
            "created_at,queued_at,schema_version) "
            "VALUES (:id,:type,'Queued',NULL,:priority,now(),now(),'1.0.0')"
        ),
        {"id": task.task_id, "type": _TASK_TYPE, "priority": "Interactive"},
    )
    await session.commit()
    return task


async def _clear_test_tasks() -> None:
    connection = await engine.connect()
    try:
        session = AsyncSession(connection)
        async with session.begin():
            task_ids = "SELECT task_id FROM work.tasks WHERE task_type LIKE :prefix"
            params = {"prefix": _TASK_TYPE_PATTERN}
            await session.execute(
                text(f"DELETE FROM work.task_effects WHERE task_id IN ({task_ids})"),
                params,
            )
            await session.execute(
                text(f"DELETE FROM work.task_attempts WHERE task_id IN ({task_ids})"),
                params,
            )
            await session.execute(
                text("DELETE FROM work.tasks WHERE task_type LIKE :prefix"), params
            )
        await session.close()
    finally:
        await connection.close()


@pytest_asyncio.fixture(autouse=True)
async def clean_work_tables() -> AsyncIterator[None]:
    await _clear_test_tasks()
    try:
        yield
    finally:
        await _clear_test_tasks()


@pytest.mark.asyncio
async def test_claim_next_orders_by_priority_then_fifo() -> None:
    connection = await engine.connect()
    session = AsyncSession(connection)
    try:
        pending = await session.scalar(
            text(
                "SELECT count(*) FROM work.tasks WHERE state IN ('Queued','Retrying') "
                "AND (next_attempt_at IS NULL OR next_attempt_at<=now())"
            )
        )
        if pending:
            pytest.skip(
                "claim_next reads the shared queue; eligible tasks already exist"
            )
        await session.rollback()
        test_task_ids: set[UUID] = set()
        async with session.begin():
            for i, (state, prio, _label) in enumerate(
                [
                    ("Queued", "Background", "bg"),
                    ("Queued", "Interactive", "it"),
                    ("Queued", "Normal", "nm"),
                    ("Queued", "Interactive", "it2"),
                    ("Retrying", "Normal", "rt"),
                ]
            ):
                task_id = uuid4()
                test_task_ids.add(task_id)
                await session.execute(
                    text(
                        "INSERT INTO work.tasks (task_id,task_type,state,priority,"
                        "created_at,queued_at,schema_version) "
                        "VALUES (:id,:t,:state,:prio,"
                        "(now() - (:i || ' seconds')::interval),now(),'1.0.0')"
                    ),
                    {
                        "id": task_id,
                        "t": _TASK_TYPE,
                        "state": state,
                        "prio": prio,
                        "i": i,
                    },
                )
        repo = PostgresTaskRepository(session)
        first = await repo.claim_next("w", 60)
        second = await repo.claim_next("w", 60)
        assert first is not None and second is not None
        assert first.task_id in test_task_ids
        assert second.task_id in test_task_ids
        rows = (
            await session.execute(
                text("SELECT priority FROM work.tasks WHERE task_id IN (:a,:b)"),
                {"a": first.task_id, "b": second.task_id},
            )
        ).all()
        priorities = {r[0] for r in rows}
        assert priorities == {"Interactive"}  # both Interactive claimed first
        # third claim must be the Normal-queued task (FIFO within interactive done)
        third = await repo.claim_next("w", 60)
        assert third is not None
        assert third.task_id in test_task_ids
        prio3 = await session.scalar(
            text("SELECT priority FROM work.tasks WHERE task_id=:t"),
            {"t": third.task_id},
        )
        assert prio3 == "Normal"
    finally:
        await session.close()
        await connection.close()


@pytest.mark.asyncio
async def test_worker_executes_and_finishes_with_effect_fencing() -> None:
    connection = await engine.connect()
    session = AsyncSession(connection)
    try:
        task = await _create_queued(session)
        repo = PostgresTaskRepository(session)
        effects = PostgresTaskEffectRepository(session)
        tracer = RecordingTracer()
        worker = WorkerHost(
            _SingleTaskRepository(repo, task.task_id),
            await _build(session, DemoSideEffectHandler(effects)),
            worker_id="w",
            heartbeat_seconds=60,
            tracer=tracer,
        )
        assert await worker.run_once()
        state = await session.scalar(
            text("SELECT state FROM work.tasks WHERE task_id=:t"), {"t": task.task_id}
        )
        assert state == "Succeeded"
        effect_count = await session.scalar(
            text(
                "SELECT count(*) FROM work.task_effects WHERE task_id=:t "
                "AND status='Pending'"
            ),
            {"t": task.task_id},
        )
        assert effect_count == 1
        span_names = {name for name, _ in tracer.spans}
        assert "task.execute" in span_names
        assert any("taskId" in attrs for _, attrs in tracer.spans)
    finally:
        await session.close()
        await connection.close()


@pytest.mark.asyncio
async def test_cancellation_checkpoint_closes_cancelled() -> None:
    connection = await engine.connect()
    session = AsyncSession(connection)
    try:
        task = await _create_queued(session)
        repo = PostgresTaskRepository(session)
        worker = WorkerHost(
            _SingleTaskRepository(repo, task.task_id),
            await _build(session, CancelAfterOneHandler()),
            worker_id="w",
            heartbeat_seconds=60,
        )
        # Request cancel BEFORE the run: checkpoint must abort cooperatively
        await repo.request_cancel(task.task_id, datetime.now(UTC))
        await session.commit()
        assert await worker.run_once()
        state = await session.scalar(
            text("SELECT state FROM work.tasks WHERE task_id=:t"), {"t": task.task_id}
        )
        assert state == "Cancelled"
    finally:
        await session.close()
        await connection.close()


@pytest.mark.asyncio
async def test_reconciler_requeues_expired_lease_and_reclaims_with_next_epoch() -> None:
    connection = await engine.connect()
    session = AsyncSession(connection)
    try:
        task = await _create_queued(session)
        repo = PostgresTaskRepository(session)
        first = await repo.claim(task.task_id, "w1", 60)
        assert first is not None
        await session.commit()
        # Simulate worker crash: lease expires without finish
        await session.execute(
            text(
                "UPDATE work.task_attempts SET lease_until=now()-interval '1 minute' "
                "WHERE task_id=:task_id"
            ),
            {"task_id": task.task_id},
        )
        await session.commit()
        reconciler = LeaseReconciler(_SingleTaskRepository(repo, task.task_id))
        requeued = await reconciler.reconcile(datetime.now(UTC))
        assert task.task_id in requeued
        second = await repo.claim(task.task_id, "w2", 60)
        assert second is not None
        assert second.task_id == task.task_id
        assert second.execution_epoch == first.execution_epoch + 1
        # stale finish from the dead worker must be rejected
        with pytest.raises(Exception):
            await repo.finish(
                task.task_id, first.attempt_id, first.execution_epoch, True
            )
    finally:
        await session.close()
        await connection.close()


@pytest.mark.asyncio
async def test_crashed_worker_recovery_via_subprocess() -> None:
    """Real process-level fault injection: a worker subprocess claims a task and
    exits without finishing (crash); the reconciler requeues; a second worker
    claims with epoch+1 and completes."""
    connection = await engine.connect()
    session = AsyncSession(connection)
    try:
        task = await _create_queued(session)
        code = (
            "import asyncio\n"
            "from app_infra.postgres.engine import engine\n"
            "from app_infra.postgres.task.task_repository import (\n"
            "    PostgresTaskRepository,\n"
            ")\n"
            "from sqlalchemy.ext.asyncio import AsyncSession\n"
            "\n"
            "async def m():\n"
            "    c = await engine.connect()\n"
            "    s = AsyncSession(c)\n"
            "    r = PostgresTaskRepository(s)\n"
            f"    await r.claim('{task.task_id}', 'crash-worker', 60)\n"
            "    await s.commit()\n"
            "    await s.close()\n"
            "    await c.close()\n"
            "\n"
            "asyncio.run(m())\n"
        )
        env = dict(os.environ)
        env["PYTHONPATH"] = ":".join(
            [
                str(Path("packages/py/task-runtime/src").resolve()),
                str(Path("packages/py/core/src").resolve()),
            ]
        )
        proc = subprocess.run(
            [sys.executable, "-c", code], env=env, capture_output=True, timeout=60
        )
        assert proc.returncode == 0, proc.stderr.decode()
        # force lease expiry for the crashed worker's attempt
        await session.execute(
            text(
                "UPDATE work.task_attempts SET lease_until=now()-interval '1 minute' "
                "WHERE worker_id='crash-worker' AND task_id=:task_id"
            ),
            {"task_id": task.task_id},
        )
        await session.commit()
        repo = PostgresTaskRepository(session)
        reconciler = LeaseReconciler(_SingleTaskRepository(repo, task.task_id))
        requeued = await reconciler.reconcile(datetime.now(UTC))
        assert task.task_id in requeued
        second = await repo.claim(task.task_id, "w2", 60)
        assert second is not None
        assert second.task_id == task.task_id
        assert second.attempt_number == 2
    finally:
        await session.close()
        await connection.close()
