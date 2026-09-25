from __future__ import annotations

import asyncio
import os
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID, uuid4

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


async def _task(
    session: AsyncSession,
    *,
    state: str = "Queued",
    next_at=None,
    actor_account_id=None,
    input_ref=None,
):
    from app_infra.postgres.task.task_repository import PostgresTaskRepository

    task_id = uuid4()
    await PostgresTaskRepository(session).create(
        SimpleNamespace(
            task_id=task_id,
            task_type="Example",
            state=state,
            stage=None,
            priority="Normal",
            actor_account_id=actor_account_id,
            workspace_id=None,
            resource_id=None,
            input_ref=input_ref,
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


async def _account(session: AsyncSession, account_id: UUID | None = None) -> UUID:
    account_id = account_id or uuid4()
    email = f"task-{account_id}@example.test"
    await session.execute(
        text(
            "INSERT INTO auth.accounts "
            "(account_id,status,primary_email,normalized_email) "
            "VALUES (:account_id,'Active',:email,:email)"
        ),
        {"account_id": account_id, "email": email},
    )
    return account_id


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
            task_id,
            claim.attempt_id,
            claim.execution_epoch + 1,
            True,
            failure_code=None,
        )


@pytest.mark.asyncio
async def test_terminal_failure_persists_code_and_successful_retry_clears_it(
    db_session: AsyncSession,
):
    from app_infra.postgres.task.task_repository import PostgresTaskRepository

    repository = PostgresTaskRepository(db_session)
    failed_id = await _task(db_session)
    failed_attempt = await repository.claim(failed_id, "worker", 60)
    assert failed_attempt is not None
    await repository.finish(
        failed_id,
        failed_attempt.attempt_id,
        failed_attempt.execution_epoch,
        False,
        failure_code="RETRY_EXHAUSTED",
    )
    failed = await repository.get(failed_id)
    assert failed is not None
    assert failed.state.value == "Failed"
    assert failed.failure_code == "RETRY_EXHAUSTED"

    retried_id = await _task(db_session)
    first_attempt = await repository.claim(retried_id, "worker", 60)
    assert first_attempt is not None
    await repository.schedule_retry(
        retried_id,
        datetime.now(UTC) - timedelta(seconds=1),
        "PREVIOUS_ATTEMPT_FAILED",
    )
    retry_attempt = await repository.claim(retried_id, "worker", 60)
    assert retry_attempt is not None
    await repository.finish(
        retried_id,
        retry_attempt.attempt_id,
        retry_attempt.execution_epoch,
        True,
        failure_code=None,
    )
    succeeded = await repository.get(retried_id)
    assert succeeded is not None
    assert succeeded.state.value == "Succeeded"
    assert succeeded.failure_code is None


@pytest.mark.asyncio
async def test_progress_update_preserves_omitted_labels_and_replaces_counts(
    db_session: AsyncSession,
):
    from app_infra.postgres.task.task_repository import PostgresTaskRepository

    task_id = await _task(db_session)
    repository = PostgresTaskRepository(db_session)
    claim = await repository.claim(task_id, "worker", 60)
    assert claim is not None
    await db_session.execute(
        text(
            "UPDATE work.tasks SET stage='Importing',"
            "progress_message_code='import.reading' WHERE task_id=:task_id"
        ),
        {"task_id": task_id},
    )

    await repository.update_progress(
        task_id,
        claim.attempt_id,
        claim.execution_epoch,
        stage=None,
        message_code=None,
        current=3,
        total=8,
        percentage=Decimal("37.50"),
    )

    row = (
        (
            await db_session.execute(
                text(
                    "SELECT stage,progress_message_code,progress_current,"
                    "progress_total,"
                    "progress_percentage,progress_updated_at FROM work.tasks "
                    "WHERE task_id=:task_id"
                ),
                {"task_id": task_id},
            )
        )
        .mappings()
        .one()
    )
    assert row["stage"] == "Importing"
    assert row["progress_message_code"] == "import.reading"
    assert row["progress_current"] == 3
    assert row["progress_total"] == 8
    assert row["progress_percentage"] == Decimal("37.50")
    assert row["progress_updated_at"] is not None


@pytest.mark.asyncio
async def test_progress_update_rejects_expired_attempt_lease(
    db_session: AsyncSession,
):
    from app_infra.postgres.task.task_repository import PostgresTaskRepository

    task_id = await _task(db_session)
    repository = PostgresTaskRepository(db_session)
    claim = await repository.claim(task_id, "worker", 60)
    assert claim is not None
    await db_session.execute(
        text(
            "UPDATE work.task_attempts "
            "SET lease_until=clock_timestamp()+interval '100 milliseconds' "
            "WHERE attempt_id=:attempt_id"
        ),
        {"attempt_id": claim.attempt_id},
    )
    await asyncio.sleep(0.2)

    with pytest.raises(StaleAttemptError):
        await repository.update_progress(
            task_id,
            claim.attempt_id,
            claim.execution_epoch,
            stage="Importing",
            message_code="import.reading",
            current=1,
            total=10,
            percentage=Decimal("10.00"),
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
async def test_retry_idempotency_replays_and_is_scoped_to_actor_and_source(
    db_session: AsyncSession,
):
    from app_core.common.exceptions import ConflictError
    from app_core.operations.task import CreateTask, RetryTask
    from app_infra.postgres.task.task_repository import PostgresTaskRepository

    actor_account_id = await _account(db_session)
    idempotency_key = uuid4()
    source_id = await _task(
        db_session,
        state="Failed",
        actor_account_id=actor_account_id,
        input_ref="asset://retry-input",
    )
    other_source_id = await _task(
        db_session, state="Failed", actor_account_id=actor_account_id
    )
    other_actor_id = await _account(db_session)
    other_actor_source_id = await _task(
        db_session, state="Failed", actor_account_id=other_actor_id
    )
    queued_source_id = await _task(db_session, actor_account_id=actor_account_id)
    repository = PostgresTaskRepository(db_session)
    retry = RetryTask(repository, CreateTask(repository))

    first = await retry.execute(source_id, actor_account_id, idempotency_key)
    replay = await retry.execute(source_id, actor_account_id, idempotency_key)

    assert replay.task_id == first.task_id
    assert replay.retry_of_task_id == source_id
    assert replay.input_ref == "asset://retry-input"
    with pytest.raises(ConflictError) as conflict:
        await retry.execute(other_source_id, actor_account_id, idempotency_key)
    assert conflict.value.error_code == "IDEMPOTENCY_KEY_CONFLICT"

    other_actor_retry = await retry.execute(
        other_actor_source_id, other_actor_id, idempotency_key
    )
    assert other_actor_retry.task_id != first.task_id

    with pytest.raises(ConflictError) as not_retryable:
        await retry.execute(queued_source_id, actor_account_id, uuid4())
    assert not_retryable.value.error_code == "TASK_NOT_RETRYABLE"
    assert (
        await db_session.scalar(
            text(
                "SELECT count(*) FROM work.tasks "
                "WHERE actor_account_id=:actor_id AND idempotency_key=:key"
            ),
            {"actor_id": actor_account_id, "key": idempotency_key},
        )
        == 1
    )


@pytest.mark.asyncio
async def test_concurrent_retry_replay_creates_one_child_task():
    from app_core.operations.task import CreateTask, RetryTask
    from app_infra.postgres.task.task_repository import PostgresTaskRepository

    actor_account_id = uuid4()
    idempotency_key = uuid4()
    async with engine.connect() as setup_connection:
        setup_session = AsyncSession(setup_connection)
        await _account(setup_session, actor_account_id)
        source_id = await _task(
            setup_session, state="Failed", actor_account_id=actor_account_id
        )
        await setup_session.commit()
        await setup_session.close()

    async def retry_in_transaction():
        async with engine.connect() as connection:
            session = AsyncSession(connection)
            async with session.begin():
                repository = PostgresTaskRepository(session)
                return await RetryTask(repository, CreateTask(repository)).execute(
                    source_id, actor_account_id, idempotency_key
                )

    first, second = await asyncio.wait_for(
        asyncio.gather(retry_in_transaction(), retry_in_transaction()), timeout=10
    )
    assert first.task_id == second.task_id

    async with engine.connect() as connection:
        result = await connection.execute(
            text(
                "SELECT count(*) FROM work.tasks WHERE actor_account_id=:actor_id "
                "AND idempotency_key=:key"
            ),
            {"actor_id": actor_account_id, "key": idempotency_key},
        )
        assert result.scalar_one() == 1


@pytest.mark.asyncio
async def test_retry_rollback_does_not_reserve_idempotency_key(
    db_session: AsyncSession,
):
    from app_core.operations.task import CreateTask, RetryTask
    from app_infra.postgres.task.task_repository import PostgresTaskRepository

    actor_account_id = uuid4()
    idempotency_key = uuid4()
    async with engine.connect() as setup_connection:
        setup_session = AsyncSession(setup_connection)
        await _account(setup_session, actor_account_id)
        source_id = await _task(
            setup_session, state="Failed", actor_account_id=actor_account_id
        )
        await setup_session.commit()
        await setup_session.close()

    repository = PostgresTaskRepository(db_session)
    retry = RetryTask(repository, CreateTask(repository))
    first = await retry.execute(source_id, actor_account_id, idempotency_key)
    await db_session.rollback()
    assert (
        await db_session.scalar(
            text(
                "SELECT count(*) FROM work.tasks "
                "WHERE actor_account_id=:actor_id AND idempotency_key=:key"
            ),
            {"actor_id": actor_account_id, "key": idempotency_key},
        )
        == 0
    )

    second = await retry.execute(source_id, actor_account_id, idempotency_key)
    assert second.task_id != first.task_id
    assert (
        await db_session.scalar(
            text(
                "SELECT count(*) FROM work.tasks "
                "WHERE actor_account_id=:actor_id AND idempotency_key=:key"
            ),
            {"actor_id": actor_account_id, "key": idempotency_key},
        )
        == 1
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
