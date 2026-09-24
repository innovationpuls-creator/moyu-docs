from __future__ import annotations

import asyncio
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest
import pytest_asyncio
from alembic import command
from alembic.config import Config
from app_core.operations.task import StaleAttemptError
from app_infra.postgres.engine import engine
from app_infra.postgres.test_database_guard import require_isolated_database
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
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


async def _task(session: AsyncSession, *, state: str = "Queued", next_at=None):
    from app_infra.postgres.task.task_repository import PostgresTaskRepository

    task_id = uuid4()
    await PostgresTaskRepository(session).create(
        SimpleNamespace(
            task_id=task_id,
            task_type="Example",
            state=state,
            stage=None,
            priority="Normal",
            actor_account_id=None,
            workspace_id=None,
            resource_id=None,
            input_ref=None,
            result_ref=None,
            retry_of_task_id=None,
            retry_count=0,
            next_attempt_at=next_at,
            cancel_requested_at=None,
            created_at=datetime.now(UTC),
            queued_at=datetime.now(UTC),
            started_at=None,
            finished_at=None,
            failure_code=None,
            schema_version="1.0.0",
        )
    )
    return task_id


@pytest.mark.asyncio
async def test_claim_is_atomic_and_only_one_concurrent_winner(db_session: AsyncSession):
    from app_infra.postgres.task.task_repository import PostgresTaskRepository

    async with engine.connect() as setup_connection:
        setup_session = AsyncSession(setup_connection)
        task_id = await _task(setup_session)
        await setup_session.commit()
        await setup_session.close()
    async with (
        engine.connect() as first_connection,
        engine.connect() as second_connection,
    ):
        first = AsyncSession(first_connection)
        second = AsyncSession(second_connection)

        async def claim(session: AsyncSession, worker_id: str):
            async with session.begin():
                return await PostgresTaskRepository(session).claim(
                    task_id, worker_id, 60
                )

        results = await asyncio.wait_for(
            asyncio.gather(
                claim(first, "worker-a"),
                claim(second, "worker-b"),
                return_exceptions=True,
            ),
            timeout=10,
        )
        winners = [result for result in results if result is not None]
        assert len(winners) == 1, repr(results)
        await first.rollback()
        await second.rollback()
        await first.close()
        await second.close()


@pytest.mark.asyncio
async def test_claim_honors_next_attempt_at(db_session: AsyncSession):
    from app_infra.postgres.task.task_repository import PostgresTaskRepository

    task_id = await _task(db_session, next_at=datetime.now(UTC) + timedelta(minutes=5))
    assert await PostgresTaskRepository(db_session).claim(task_id, "worker", 60) is None


@pytest.mark.asyncio
async def test_stale_epoch_heartbeat_and_finish_are_rejected(db_session: AsyncSession):
    from app_infra.postgres.task.task_repository import PostgresTaskRepository

    task_id = await _task(db_session)
    repository = PostgresTaskRepository(db_session)
    claim = await repository.claim(task_id, "worker", 60)
    assert claim is not None
    with pytest.raises(StaleAttemptError):
        await repository.heartbeat(
            task_id, claim.attempt_id, claim.execution_epoch + 1, 60
        )
    with pytest.raises(StaleAttemptError):
        await repository.finish(
            task_id, claim.attempt_id, claim.execution_epoch + 1, True
        )


@pytest.mark.asyncio
async def test_retry_cancel_and_effect_uniqueness(db_session: AsyncSession):
    from app_infra.postgres.task.effect_repository import PostgresTaskEffectRepository
    from app_infra.postgres.task.task_repository import PostgresTaskRepository

    task_id = await _task(db_session)
    repository = PostgresTaskRepository(db_session)
    claim = await repository.claim(task_id, "worker", 30)
    assert claim is not None
    effect = PostgresTaskEffectRepository(db_session)
    task = await repository.get(task_id)
    assert task is not None and task.current_attempt_id is not None
    await effect.record_effect(
        task_id,
        "key",
        "Email",
        {"id": "1"},
        attempt_id=task.current_attempt_id,
        execution_epoch=task.execution_epoch,
    )
    with pytest.raises(IntegrityError):
        async with db_session.begin_nested():
            await effect.record_effect(
                task_id,
                "key",
                "Email",
                {"id": "1"},
                attempt_id=task.current_attempt_id,
                execution_epoch=task.execution_epoch,
            )


@pytest.mark.asyncio
async def test_task_and_attempt_rollback_with_caller_transaction(
    db_session: AsyncSession,
):
    from app_infra.postgres.task.task_repository import PostgresTaskRepository

    task_id = await _task(db_session)
    claim = await PostgresTaskRepository(db_session).claim(task_id, "worker", 60)
    assert claim is not None
    await db_session.rollback()
    assert (
        await db_session.scalar(
            text("SELECT count(*) FROM work.tasks WHERE task_id=:id"), {"id": task_id}
        )
        == 0
    )
