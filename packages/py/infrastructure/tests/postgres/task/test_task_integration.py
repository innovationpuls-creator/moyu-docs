from __future__ import annotations

import os
from pathlib import Path

import pytest
import pytest_asyncio
from alembic import command
from alembic.config import Config
from app_core.operations.task import (
    ClaimTask,
    CreateTask,
    FinishAttempt,
    ReconcileTasks,
    ResumeTask,
    StaleAttemptError,
)
from app_infra.postgres.engine import engine
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
async def test_create_claim_rehydrate_heartbeat_finish(
    db_session: AsyncSession,
) -> None:
    repository = PostgresTaskRepository(db_session)
    created = await CreateTask(repository).execute("Integration")
    assert created.state.value == "Queued"
    claim = await ClaimTask(repository).execute(created.task_id, "worker", 60)
    assert claim is not None
    assert await repository.heartbeat(
        created.task_id, claim.attempt_id, claim.execution_epoch, 60
    )
    await FinishAttempt(repository).execute(
        created.task_id, claim.attempt_id, claim.execution_epoch, succeeded=True
    )
    row = (
        await db_session.execute(
            text("SELECT state FROM work.tasks WHERE task_id=:id"),
            {"id": created.task_id},
        )
    ).one()
    assert row.state == "Succeeded"


@pytest.mark.asyncio
async def test_recover_requeues_and_reclaims_with_next_epoch(
    db_session: AsyncSession,
) -> None:
    repository = PostgresTaskRepository(db_session)
    created = await CreateTask(repository).execute("Recover")
    first = await repository.claim(created.task_id, "worker-a", 60)
    assert first is not None
    await db_session.execute(
        text(
            "UPDATE work.task_attempts SET lease_until=now()-interval '1 second' "
            "WHERE attempt_id=:id"
        ),
        {"id": first.attempt_id},
    )
    recovered = await ReconcileTasks(repository).recover(created.task_id)
    assert recovered.state.value == "Queued"
    second = await repository.claim(created.task_id, "worker-b", 60)
    assert second is not None
    assert second.execution_epoch == first.execution_epoch + 1


@pytest.mark.asyncio
async def test_resume_waiting_for_user_releases_lease_and_requeues(
    db_session: AsyncSession,
) -> None:
    repository = PostgresTaskRepository(db_session)
    created = await CreateTask(repository).execute("Resume")
    claim = await repository.claim(created.task_id, "worker", 60)
    assert claim is not None
    await db_session.execute(
        text("UPDATE work.tasks SET state='WaitingForUser' WHERE task_id=:id"),
        {"id": created.task_id},
    )
    resumed = await ResumeTask(repository).execute(created.task_id)
    assert resumed.state.value == "Queued"
    assert await repository.claim(created.task_id, "worker-2", 60) is not None


@pytest.mark.asyncio
async def test_finish_with_stale_epoch_is_rejected_after_reclaim(
    db_session: AsyncSession,
) -> None:
    repository = PostgresTaskRepository(db_session)
    created = await CreateTask(repository).execute("Stale")
    first = await repository.claim(created.task_id, "worker-a", 60)
    assert first is not None
    await repository.release_for_recovery(
        created.task_id, first.attempt_id, first.execution_epoch
    )
    second = await repository.claim(created.task_id, "worker-b", 60)
    assert second is not None
    with pytest.raises(StaleAttemptError):
        await FinishAttempt(repository).execute(
            created.task_id, first.attempt_id, first.execution_epoch, succeeded=True
        )
