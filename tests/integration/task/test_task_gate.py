from __future__ import annotations

import asyncio
import os
from collections.abc import AsyncGenerator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pytest
import pytest_asyncio
from alembic import command
from alembic.config import Config
from app_infra.postgres.engine import engine
from app_infra.postgres.task.effect_repository import PostgresTaskEffectRepository
from app_infra.postgres.task.task_repository import PostgresTaskRepository
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


async def _create_task(session: AsyncSession, priority: str = "Normal"):
    task_id = uuid4()
    await session.execute(
        text(
            "INSERT INTO work.tasks (task_id,task_type,state,priority,created_at,"
            "queued_at,schema_version) VALUES (:id,'gate','Queued',:priority,now(),"
            "now(),'1.0.0')"
        ),
        {"id": task_id, "priority": priority},
    )
    return task_id


@pytest.mark.asyncio
async def test_duplicate_effect_key_has_one_durable_row(
    db_session: AsyncSession,
) -> None:
    task_id = await _create_task(db_session)
    repo = PostgresTaskRepository(db_session)
    claim = await repo.claim(task_id, "w", 60)
    assert claim is not None
    effects = PostgresTaskEffectRepository(db_session)
    await effects.record_effect(
        task_id,
        "gate-effect",
        "Gate",
        {"ref": "identity"},
        attempt_id=claim.attempt_id,
        execution_epoch=claim.execution_epoch,
    )
    with pytest.raises(IntegrityError):
        async with db_session.begin_nested():
            await effects.record_effect(
                task_id,
                "gate-effect",
                "Gate",
                {"ref": "identity"},
                attempt_id=claim.attempt_id,
                execution_epoch=claim.execution_epoch,
            )


@pytest.mark.asyncio
async def test_priority_claim_does_not_starve_background(
    db_session: AsyncSession,
) -> None:
    await db_session.execute(
        text(
            "UPDATE work.tasks SET next_attempt_at=now()+interval '1 day' "
            "WHERE state IN ('Queued','Retrying')"
        )
    )
    background = await _create_task(db_session, "Background")
    await db_session.execute(
        text(
            "UPDATE work.tasks SET queued_at=now()-interval '5 minutes' "
            "WHERE task_id=:id"
        ),
        {"id": background},
    )
    repository = PostgresTaskRepository(db_session)
    for _ in range(4):
        await _create_task(db_session, "Interactive")
        claimed = await repository.claim_next("fair-worker", 60)
        assert claimed is not None
        if claimed.task_id == background:
            return
    pytest.fail("aged Background task was starved by new Interactive tasks")


@pytest.mark.asyncio
async def test_lost_delivery_reconciliation_uses_postgres_state(
    db_session: AsyncSession,
) -> None:
    task_id = await _create_task(db_session)
    repository = PostgresTaskRepository(db_session)
    assert await repository.claim(task_id, "lost-delivery-worker", 60) is not None
    await db_session.execute(
        text("UPDATE work.task_attempts SET lease_until=:expired WHERE task_id=:id"),
        {"expired": datetime.now(UTC) - timedelta(seconds=1), "id": task_id},
    )
    expired = await repository.find_expired_leases(datetime.now(UTC))
    assert task_id in expired


@pytest.mark.asyncio
async def test_retry_exhaustion_is_failed_and_diagnosable(
    db_session: AsyncSession,
) -> None:
    task_id = await _create_task(db_session)
    await db_session.execute(
        text(
            "UPDATE work.tasks SET state='Failed',failure_code='RETRY_EXHAUSTED' "
            "WHERE task_id=:id"
        ),
        {"id": task_id},
    )
    row = (
        await db_session.execute(
            text("SELECT state,failure_code FROM work.tasks WHERE task_id=:id"),
            {"id": task_id},
        )
    ).one()
    assert row == ("Failed", "RETRY_EXHAUSTED")


@pytest.mark.asyncio
async def test_two_process_claims_have_one_authoritative_winner(
    db_session: AsyncSession,
) -> None:
    async with engine.connect() as setup_connection:
        setup_session = AsyncSession(setup_connection)
        task_id = await _create_task(setup_session)
        await setup_session.commit()
        await setup_session.close()
    async with (
        engine.connect() as first_connection,
        engine.connect() as second_connection,
    ):
        first, second = AsyncSession(first_connection), AsyncSession(second_connection)
        results = await asyncio.gather(
            _claim_transaction(first, task_id, "process-a"),
            _claim_transaction(second, task_id, "process-b"),
        )
        assert sum(result is not None for result in results) == 1
        await first.close()
        await second.close()


async def _claim_transaction(session: AsyncSession, task_id, worker_id: str):
    async with session.begin():
        return await PostgresTaskRepository(session).claim(task_id, worker_id, 60)
