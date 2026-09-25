"""Runtime-slice evidence for Async Task scenarios.

These bindings drive Core/runtime and PostgreSQL directly, without HTTP.
No API/client contracts are introduced by this generic runtime slice.
"""

from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pytest
import pytest_asyncio
from alembic import command
from alembic.config import Config
from app_core.operations.task import (
    CreateTask,
    ReconcileTasks,
    ResumeTask,
)
from app_core.operations.task.domain import (
    Priority,
    Task,
    TaskState,
    TaskTransitionError,
)
from app_infra.postgres.engine import engine
from app_infra.postgres.task.effect_repository import PostgresTaskEffectRepository
from app_infra.postgres.task.task_repository import PostgresTaskRepository
from app_infra.postgres.test_database_guard import require_isolated_database
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

DATABASE_URL = "postgresql+psycopg://torch@localhost:5432/dom_workspace_lifecycle_test"


@pytest_asyncio.fixture(scope="module", autouse=True)
async def migrated_database() -> None:
    database_url = require_isolated_database(os.environ["DATABASE_URL"])
    assert database_url == DATABASE_URL
    config = Config(str(Path("migrations/postgres/alembic.ini")))
    config.set_main_option("sqlalchemy.url", database_url)
    command.upgrade(config, "head")


@pytest_asyncio.fixture
async def db_session() -> AsyncSession:
    async with engine.connect() as connection:
        transaction = await connection.begin()
        factory = async_sessionmaker(
            bind=connection,
            expire_on_commit=False,
            class_=AsyncSession,
            join_transaction_mode="create_savepoint",
        )
        async with factory() as session:
            yield session
            await session.rollback()
        await transaction.rollback()


@pytest.mark.asyncio
async def test_duplicate_create_identity_runtime_slice(
    db_session: AsyncSession,
) -> None:
    repository = PostgresTaskRepository(db_session)
    task_id = uuid4()
    task = Task(task_id, "bdd", Priority.NORMAL)
    task.queue()
    await repository.create(task)
    duplicate = Task(task_id, "bdd", Priority.NORMAL)
    duplicate.queue()
    assert await repository.create(duplicate) is False
    row_count = await db_session.scalar(
        text("SELECT count(*) FROM work.tasks WHERE task_id=:id"),
        {"id": task_id},
    )
    assert row_count == 1


@pytest.mark.asyncio
async def test_illegal_transition_rejected() -> None:
    task = Task.create("bdd")
    task.queue()
    task.start()
    task.succeed()
    with pytest.raises(TaskTransitionError):
        task.start()


@pytest.mark.asyncio
async def test_create_rollback_leaves_no_task(db_session: AsyncSession) -> None:
    repository = PostgresTaskRepository(db_session)
    task = await CreateTask(repository).execute("bdd")
    await db_session.rollback()
    assert (
        await db_session.scalar(
            text("SELECT count(*) FROM work.tasks WHERE task_id=:id"),
            {"id": task.task_id},
        )
        == 0
    )


@pytest.mark.asyncio
async def test_expired_lease_recovery_fences_previous_attempt(
    db_session: AsyncSession,
) -> None:
    repository = PostgresTaskRepository(db_session)
    task = await CreateTask(repository).execute("bdd")
    first = await repository.claim(task.task_id, "bdd-a", 60)
    assert first is not None
    await db_session.execute(
        text("UPDATE work.task_attempts SET lease_until=:expired WHERE attempt_id=:id"),
        {"expired": datetime.now(UTC) - timedelta(seconds=1), "id": first.attempt_id},
    )
    await ReconcileTasks(repository).recover(task.task_id)
    second = await repository.claim(task.task_id, "bdd-b", 60)
    assert second is not None
    assert second.execution_epoch == first.execution_epoch + 1


@pytest.mark.asyncio
async def test_duplicate_effect_is_idempotent_by_database_key(
    db_session: AsyncSession,
) -> None:
    repository = PostgresTaskRepository(db_session)
    task = await CreateTask(repository).execute("bdd")
    claim = await repository.claim(task.task_id, "bdd", 60)
    assert claim is not None
    effects = PostgresTaskEffectRepository(db_session)
    await effects.record_effect(
        task.task_id,
        "bdd-effect",
        "test",
        {"ref": "x"},
        attempt_id=claim.attempt_id,
        execution_epoch=claim.execution_epoch,
    )
    with pytest.raises(Exception):
        async with db_session.begin_nested():
            await effects.record_effect(
                task.task_id,
                "bdd-effect",
                "test",
                {"ref": "x"},
                attempt_id=claim.attempt_id,
                execution_epoch=claim.execution_epoch,
            )


@pytest.mark.asyncio
async def test_lost_delivery_state_is_reconcilable(db_session: AsyncSession) -> None:
    repository = PostgresTaskRepository(db_session)
    task = await CreateTask(repository).execute("bdd")
    assert await repository.claim(task.task_id, "bdd", 60) is not None
    await db_session.execute(
        text("UPDATE work.task_attempts SET lease_until=:expired WHERE task_id=:id"),
        {"expired": datetime.now(UTC) - timedelta(seconds=1), "id": task.task_id},
    )
    assert task.task_id in await repository.find_expired_leases(datetime.now(UTC))


@pytest.mark.asyncio
async def test_priority_fairness_has_background_candidate(
    db_session: AsyncSession,
) -> None:
    await db_session.execute(
        text(
            "UPDATE work.tasks SET next_attempt_at=now()+interval '1 day' "
            "WHERE state IN ('Queued','Retrying')"
        )
    )
    repository = PostgresTaskRepository(db_session)
    background = Task.create("background", priority=Priority.BACKGROUND)
    background.queue()
    await repository.create(background)
    for _ in range(2):
        interactive = Task.create("interactive", priority=Priority.INTERACTIVE)
        interactive.queue()
        await repository.create(interactive)
    claimed = [await repository.claim_next("bdd", 60) for _ in range(3)]
    assert any(
        item is not None and item.task_id == background.task_id for item in claimed
    )


@pytest.mark.asyncio
async def test_unknown_schema_is_observable_without_payload_guessing(
    db_session: AsyncSession,
) -> None:
    repository = PostgresTaskRepository(db_session)
    task = Task.create("bdd")
    task.queue()
    task.schema_version = "unknown"
    await repository.create(task)
    loaded = await repository.get(task.task_id)
    assert loaded is not None and loaded.schema_version == "unknown"


@pytest.mark.asyncio
async def test_resume_waiting_for_user_runtime_path(db_session: AsyncSession) -> None:
    repository = PostgresTaskRepository(db_session)
    task = await CreateTask(repository).execute("bdd")
    claim = await repository.claim(task.task_id, "bdd", 60)
    assert claim is not None
    await db_session.execute(
        text("UPDATE work.tasks SET state='WaitingForUser' WHERE task_id=:id"),
        {"id": task.task_id},
    )
    resumed = await ResumeTask(repository).execute(task.task_id)
    assert resumed.state is TaskState.QUEUED


@pytest.mark.asyncio
@pytest.mark.skip(
    reason="Runtime slice has no domain consumer retry-budget/dead-letter policy"
)
async def test_exhausted_delivery_dead_letter_diagnostics() -> None:
    pass


@pytest.mark.asyncio
@pytest.mark.skip(reason="Runtime slice has no account authorization re-check consumer")
async def test_authorization_recheck_before_execution() -> None:
    pass


@pytest.mark.asyncio
@pytest.mark.skip(reason="Runtime slice has no disabled-account checkpoint consumer")
async def test_disabled_account_checkpoint_cancellation() -> None:
    pass


@pytest.mark.asyncio
@pytest.mark.skip(
    reason="Runtime slice has no consumer-specific cancellation checkpoint"
)
async def test_cancellation_waits_for_consumer_checkpoint() -> None:
    pass
