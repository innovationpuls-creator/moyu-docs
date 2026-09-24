from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
import pytest_asyncio
from alembic import command
from alembic.config import Config
from app_infra.postgres.engine import engine
from app_infra.postgres.task.diagnostics import (
    FailedTaskDiagnostic,
    PostgresTaskDiagnostics,
)
from app_infra.postgres.task.events import PostgresTaskEventPublisher
from app_infra.postgres.task.task_repository import PostgresTaskRepository
from app_infra.postgres.test_database_guard import require_isolated_database
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from task_runtime.domain import Task

DATABASE_URL = "postgresql+psycopg://torch@localhost:5432/dom_workspace_lifecycle_test"


@pytest_asyncio.fixture(scope="module", autouse=True)
async def migrated_database() -> None:
    database_url = require_isolated_database(os.environ["DATABASE_URL"])
    assert database_url == DATABASE_URL
    config = Config(str(Path("migrations/postgres/alembic.ini")))
    config.set_main_option("sqlalchemy.url", database_url)
    command.upgrade(config, "head")


@pytest_asyncio.fixture(autouse=True)
async def clean_work_tables() -> None:
    connection = await engine.connect()
    try:
        session = AsyncSession(connection)
        async with session.begin():
            await session.execute(text("DELETE FROM integration.outbox_events"))
            await session.execute(text("DELETE FROM work.task_effects"))
            await session.execute(text("DELETE FROM work.task_attempts"))
            await session.execute(text("DELETE FROM work.tasks"))
        await session.close()
    finally:
        await connection.close()


async def _create(session: AsyncSession, repo: PostgresTaskRepository) -> Task:
    task = Task.create("demo")
    task.queue()  # Created -> Queued so claim can pick it up
    await repo.create(task)
    return task


async def _subjects(session: AsyncSession, task_id) -> list[str]:
    rows = await session.execute(
        text(
            "SELECT event_type FROM integration.outbox_events "
            "WHERE aggregate_id=:id ORDER BY created_at"
        ),
        {"id": task_id},
    )
    return [r[0] for r in rows.all()]


@pytest.mark.asyncio
async def test_create_and_claim_emits_created_queued_started_atomically() -> None:
    connection = await engine.connect()
    session = AsyncSession(connection)
    try:
        publisher = PostgresTaskEventPublisher(session)
        repo = PostgresTaskRepository(session, event_publisher=publisher)
        async with session.begin():
            task = await _create(session, repo)
            claim = await repo.claim(task.task_id, "w", 60)
            assert claim is not None
            subjects = await _subjects(session, task.task_id)
        # create emits Created+Queued, claim emits Started: exactly 3 facts,
        # written atomically in the caller transaction
        assert subjects == [
            "event.task.created.v1",
            "event.task.queued.v1",
            "event.task.started.v1",
        ]
    finally:
        await session.close()
        await connection.close()


@pytest.mark.asyncio
async def test_rollback_drops_outbox_facts() -> None:
    connection = await engine.connect()
    session = AsyncSession(connection)
    try:
        publisher = PostgresTaskEventPublisher(session)
        repo = PostgresTaskRepository(session, event_publisher=publisher)
        try:
            async with session.begin():
                task = await _create(session, repo)
                await repo.claim(task.task_id, "w", 60)
                raise RuntimeError("boom")
        except RuntimeError:
            pass
        async with session.begin():
            count = await session.scalar(
                text(
                    "SELECT count(*) FROM integration.outbox_events "
                    "WHERE aggregate_id=:id"
                ),
                {"id": task.task_id},
            )
        assert count == 0
    finally:
        await session.close()
        await connection.close()


@pytest.mark.asyncio
async def test_success_cancel_and_retry_event_sequences() -> None:
    connection = await engine.connect()
    session = AsyncSession(connection)
    try:
        publisher = PostgresTaskEventPublisher(session)
        repo = PostgresTaskRepository(session, event_publisher=publisher)
        async with session.begin():
            # succeeded path
            t1 = await _create(session, repo)
            c1 = await repo.claim(t1.task_id, "w", 60)
            assert c1 is not None
            await repo.finish(t1.task_id, c1.attempt_id, c1.execution_epoch, True)
            # cooperatively cancelled while Running
            t2 = await _create(session, repo)
            c2 = await repo.claim(t2.task_id, "w", 60)
            assert c2 is not None
            await repo.finish_cancelled(t2.task_id, c2.attempt_id, c2.execution_epoch)
            # retry scheduled while Running (handler decides recoverable)
            t3 = await _create(session, repo)
            c3 = await repo.claim(t3.task_id, "w", 60)
            assert c3 is not None
            await repo.schedule_retry(t3.task_id, datetime.now(UTC), "recoverable")
        subjects1 = await _subjects(session, t1.task_id)
        subjects2 = await _subjects(session, t2.task_id)
        subjects3 = await _subjects(session, t3.task_id)
        assert subjects1 == [
            "event.task.created.v1",
            "event.task.queued.v1",
            "event.task.started.v1",
            "event.task.succeeded.v1",
        ]
        assert subjects2[-1] == "event.task.cancelled.v1"
        assert subjects3[-1] == "event.task.retry-scheduled.v1"
    finally:
        await session.close()
        await connection.close()


@pytest.mark.asyncio
async def test_diagnostics_links_failed_task_with_outbox_event() -> None:
    connection = await engine.connect()
    session = AsyncSession(connection)
    try:
        publisher = PostgresTaskEventPublisher(session)
        repo = PostgresTaskRepository(session, event_publisher=publisher)
        diagnostics = PostgresTaskDiagnostics(session)
        async with session.begin():
            task = await _create(session, repo)
            claim = await repo.claim(task.task_id, "w", 60)
            assert claim is not None
            await repo.schedule_retry(
                task.task_id, datetime.now(UTC) - timedelta(minutes=1), "exhausted"
            )
            # back to Running for the terminal close, then fail
            claim2 = await repo.claim(task.task_id, "w2", 60)
            assert claim2 is not None
            await repo.finish(
                task.task_id, claim2.attempt_id, claim2.execution_epoch, False
            )
        async with session.begin():
            result = await diagnostics.failed_at_maturity()
        assert any(getattr(r, "task_id", None) == task.task_id for r in result)
    finally:
        await session.close()
        await connection.close()


def test_diagnostic_shape() -> None:
    from typing import get_type_hints

    hints = get_type_hints(FailedTaskDiagnostic)
    assert "task_id" in hints
    assert "failure_code" in hints
    assert "attempt_id" in hints
    assert "outbox_event_id" in hints
