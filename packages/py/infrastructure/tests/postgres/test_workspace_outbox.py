from __future__ import annotations

import os
from uuid import uuid4

import pytest
import pytest_asyncio
from app_infra.postgres.engine import engine
from app_infra.postgres.test_database_guard import require_isolated_database
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


@pytest_asyncio.fixture(scope="module", autouse=True)
async def require_test_database() -> None:
    require_isolated_database(os.environ["DATABASE_URL"])


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
async def test_lifecycle_event_publisher_inserts_outbox_row(
    db_session: AsyncSession,
) -> None:
    from app_core.workspace.ports.events import LifecycleEvent
    from app_infra.postgres.workspace_event_publisher import (
        PostgresLifecycleEventPublisher,
    )

    event = LifecycleEvent.create(
        "ProjectArchived",
        "event.workspace.project-archived.v1",
        uuid4(),
        {"projectId": str(uuid4())},
    )

    publisher = PostgresLifecycleEventPublisher(db_session)
    await publisher.publish(event)
    await publisher.publish(event)
    row = (
        (
            await db_session.execute(
                text(
                    "SELECT event_id, event_type, aggregate_id, payload "
                    "FROM integration.outbox_events WHERE event_id=:event_id"
                ),
                {"event_id": event.event_id},
            )
        )
        .mappings()
        .one()
    )

    assert row["event_id"] == event.event_id
    assert row["event_type"] == event.event_subject
    assert row["aggregate_id"] == event.aggregate_id
    assert row["payload"]["eventType"] == event.event_type
    count = await db_session.scalar(
        text("SELECT count(*) FROM integration.outbox_events WHERE event_id=:event_id"),
        {"event_id": event.event_id},
    )
    assert count == 1


@pytest.mark.asyncio
async def test_lifecycle_event_rolls_back_with_caller_transaction(
    db_session: AsyncSession,
) -> None:
    from app_core.workspace.ports.events import LifecycleEvent
    from app_infra.postgres.workspace_event_publisher import (
        PostgresLifecycleEventPublisher,
    )

    event = LifecycleEvent.create(
        "FolderCreated",
        "event.workspace.folder-created.v1",
        uuid4(),
        {"folderId": str(uuid4())},
    )
    await PostgresLifecycleEventPublisher(db_session).publish(event)
    await db_session.rollback()

    row = await db_session.scalar(
        text("SELECT event_id FROM integration.outbox_events WHERE event_id=:event_id"),
        {"event_id": event.event_id},
    )
    assert row is None
