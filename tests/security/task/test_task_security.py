from __future__ import annotations

import os
from collections.abc import AsyncGenerator
from pathlib import Path
from uuid import uuid4

import pytest
import pytest_asyncio
from alembic import command
from alembic.config import Config
from app_core.operations.task import StaleAttemptError
from app_infra.postgres.engine import engine
from app_infra.postgres.task.task_repository import PostgresTaskRepository
from app_infra.postgres.test_database_guard import require_isolated_database
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from task_runtime.domain import Task
from task_runtime.registry import HandlerRegistry
from task_runtime.runtime import WorkerHost

DATABASE_URL = "postgresql+psycopg://torch@localhost:5432/dom_workspace_lifecycle_test"


@pytest_asyncio.fixture(scope="module", autouse=True)
async def migrated_database() -> None:
    database_url = require_isolated_database(os.environ["DATABASE_URL"])
    assert database_url == DATABASE_URL
    config = Config(str(Path("migrations/postgres/alembic.ini")))
    config.set_main_option("sqlalchemy.url", database_url)
    command.upgrade(config, "head")


@pytest_asyncio.fixture
async def db_session() -> AsyncGenerator[AsyncSession, None]:
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
async def test_secret_payload_is_not_persisted(db_session: AsyncSession) -> None:
    secret = "super-secret-token"
    task_id = uuid4()
    task = Task.create(
        "secure",
        priority=__import__(
            "task_runtime.domain", fromlist=["Priority"]
        ).Priority.NORMAL,
    )
    task.task_id = task_id
    task.input_ref = "asset://opaque-input"
    await PostgresTaskRepository(db_session).create(task)
    rows = await db_session.execute(
        text("SELECT input_ref,result_ref FROM work.tasks WHERE task_id=:id"),
        {"id": task_id},
    )
    values = " ".join(str(value) for row in rows for value in row)
    assert secret not in values
    assert (
        await db_session.scalar(
            text(
                "SELECT count(*) FROM work.task_effects "
                "WHERE target_ref::text LIKE :secret"
            ),
            {"secret": f"%{secret}%"},
        )
        == 0
    )


@pytest.mark.asyncio
async def test_stale_epoch_finish_rejected(db_session: AsyncSession) -> None:
    task_id = uuid4()
    await db_session.execute(
        text(
            "INSERT INTO work.tasks (task_id,task_type,state,priority,created_at,"
            "queued_at,schema_version) VALUES "
            "(:id,'secure','Queued','Normal',now(),now(),'1.0.0')"
        ),
        {"id": task_id},
    )
    repository = PostgresTaskRepository(db_session)
    claim = await repository.claim(task_id, "secure-worker", 60)
    assert claim is not None
    with pytest.raises(StaleAttemptError):
        await repository.finish(
            task_id, claim.attempt_id, claim.execution_epoch + 99, True
        )


@pytest.mark.asyncio
async def test_unknown_schema_version_is_terminalized_by_runtime(
    db_session: AsyncSession,
) -> None:
    task_id = uuid4()
    await db_session.execute(
        text(
            "INSERT INTO work.tasks (task_id,task_type,state,priority,created_at,"
            "queued_at,schema_version) VALUES "
            "(:id,'secure','Queued','Normal',now(),now(),'9.9.9')"
        ),
        {"id": task_id},
    )
    repository = PostgresTaskRepository(db_session)
    worker = WorkerHost(
        repository,
        HandlerRegistry(),
        worker_id="secure-worker",
        heartbeat_seconds=60,
    )
    assert await worker.run_once()
    state = await db_session.scalar(
        text("SELECT state FROM work.tasks WHERE task_id=:id"), {"id": task_id}
    )
    assert state == "Failed"
