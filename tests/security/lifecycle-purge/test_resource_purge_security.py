"""Arch 09/25: expired Trashed Resources are physically purged (retention),
sibling names freed only by the purge (frozen product rule)."""

from __future__ import annotations

from collections.abc import AsyncGenerator
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
from alembic import command
from alembic.config import Config
from app_core.operations.task import CreateTask
from app_core.resource.purge import PurgeResource
from app_infra.postgres.engine import engine
from app_infra.postgres.permission_resource_cleanup_repository import (
    PostgresPermissionResourceCleanupRepository,
)
from app_infra.postgres.resource.resource_purge_enqueuer import (
    PostgresResourcePurgeEnqueuer,
)
from app_infra.postgres.resource.resource_purge_repository import (
    PostgresResourcePurgeRepository,
)
from app_infra.postgres.resource.resource_repository import (
    PostgresResourceRepository,
)
from app_infra.postgres.task.task_repository import PostgresTaskRepository
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from task_runtime.registry import HandlerRegistry, HandlerSpec
from task_runtime.runtime import WorkerHost

from workers.maintenance.task_handlers.resource_purge import ResourcePurgeHandler

DATABASE_URL = "postgresql+psycopg://torch@localhost:5432/dom_workspace_lifecycle_test"


@pytest_asyncio.fixture(scope="module", autouse=True)
async def migrated_database() -> None:
    config = Config(str("migrations/postgres/alembic.ini"))
    config.set_main_option("sqlalchemy.url", DATABASE_URL)
    command.upgrade(config, "head")


@pytest_asyncio.fixture
async def db_session() -> AsyncGenerator[AsyncSession, None]:
    conn = await engine.connect()
    tx = await conn.begin()
    factory = async_sessionmaker(bind=conn, expire_on_commit=False, class_=AsyncSession)
    session = factory()
    try:
        yield session
    finally:
        await session.close()
        await tx.rollback()
        await conn.close()


async def _seed_trashed(session: AsyncSession) -> tuple[UUID, UUID]:
    account_id = uuid4()
    workspace_id = uuid4()
    project_id = uuid4()
    await session.execute(
        text(
            "INSERT INTO auth.accounts "
            "(account_id,status,primary_email,normalized_email) "
            "VALUES (:a,'Active',:e,:e)"
        ),
        {"a": account_id, "e": f"rp-{account_id}@test"},
    )
    await session.execute(
        text(
            "INSERT INTO core.workspaces "
            "(workspace_id,name,status,created_by,created_at,updated_at) "
            "VALUES (:w,'P','Active',:a,now(),now())"
        ),
        {"w": workspace_id, "a": account_id},
    )
    await session.execute(
        text(
            "INSERT INTO core.workspace_members "
            "(workspace_id,account_id,membership_kind) "
            "VALUES (:w,:a,'Owner')"
        ),
        {"w": workspace_id, "a": account_id},
    )
    await session.execute(
        text(
            "INSERT INTO core.projects "
            "(project_id,workspace_id,name,normalized_name,lifecycle,"
            "created_by,created_at,updated_at) "
            "VALUES (:p,:w,'P','p','Active',:a,now(),now())"
        ),
        {"p": project_id, "w": workspace_id, "a": account_id},
    )
    resource = await PostgresResourceRepository(session).create(
        project_id=project_id,
        resource_type="document",
        name="Old",
        normalized_name="old",
    )
    await session.execute(
        text(
            "UPDATE core.resources SET lifecycle='Trashed',"
            "trashed_at=:at WHERE resource_id=:id"
        ),
        {"at": datetime.now(UTC) - timedelta(days=30), "id": resource.resource_id},
    )
    await session.execute(
        text(
            "INSERT INTO collab.resource_update_journal "
            "(resource_id,journal_seq,ownership_epoch,update_bytes,update_hash) "
            "VALUES (:id,1,1,:b,:h)"
        ),
        {"id": resource.resource_id, "b": b"x", "h": "h"},
    )
    return resource.resource_id, project_id


@pytest.mark.asyncio
async def test_expired_trashed_resource_is_physically_purged(
    db_session: AsyncSession,
) -> None:
    async with db_session.begin():
        resource_id, project_id = await _seed_trashed(db_session)
    async with db_session.begin():
        enqueued = await PostgresResourcePurgeEnqueuer(
            db_session, CreateTask(PostgresTaskRepository(db_session))
        ).enqueue()
    assert enqueued == 1
    async with db_session.begin():
        task_id = await db_session.scalar(
            text(
                "SELECT task_id FROM work.tasks WHERE task_type='resource.purge' "
                "AND input_ref=:resource_id ORDER BY created_at DESC LIMIT 1"
            ),
            {"resource_id": str(resource_id)},
        )
    assert task_id is not None
    async with db_session.begin():
        await db_session.execute(
            text(
                "UPDATE work.tasks SET next_attempt_at=now()+interval '1 day' "
                "WHERE state IN ('Queued','Retrying') AND task_id<>:task_id"
            ),
            {"task_id": task_id},
        )
    effects = SimpleNamespace(record_effect=lambda *a, **k: None)
    audit_rows: list[tuple[str, object]] = []

    class _Audit:
        async def record(self, **kwargs: object) -> None:
            audit_rows.append((str(kwargs["action"]), kwargs["target_id"]))

    handler = ResourcePurgeHandler(
        PurgeResource(
            PostgresResourcePurgeRepository(
                db_session, PostgresPermissionResourceCleanupRepository(db_session)
            )
        ),
        effects,
        audit=_Audit(),
    )
    registry = HandlerRegistry()
    registry.register(HandlerSpec("resource.purge", handler))
    worker = WorkerHost(
        PostgresTaskRepository(db_session),
        registry,
        worker_id="rp-bdd",
        heartbeat_seconds=60,
    )
    async with db_session.begin():
        assert await worker.run_once()
    async with db_session.begin():
        row = await db_session.scalar(
            text("SELECT 1 FROM core.resources WHERE resource_id=:id"),
            {"id": resource_id},
        )
        journal_left = await db_session.scalar(
            text(
                "SELECT count(*) FROM collab.resource_update_journal "
                "WHERE resource_id=:id"
            ),
            {"id": resource_id},
        )
        sibling = await db_session.scalar(
            text(
                "SELECT 1 FROM core.resources WHERE project_id=:p "
                "AND normalized_name='old'"
            ),
            {"p": project_id},
        )
    assert row is None  # physical cleanup happened
    assert journal_left == 0
    assert sibling is None  # name is free ONLY after the purge
    assert any(action == "resource.purged" for action, _ in audit_rows)
