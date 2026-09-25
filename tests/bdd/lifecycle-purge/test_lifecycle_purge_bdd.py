from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
from alembic import command
from alembic.config import Config
from app_core.workspace.application.purge import PurgeWorkspace
from app_core.workspace.ports.purge import WorkspaceMembershipCleanupPort
from app_infra.postgres.engine import engine
from app_infra.postgres.permission_workspace_repository import (
    PostgresWorkspaceMembershipRepository,
)
from app_infra.postgres.task.effect_repository import PostgresTaskEffectRepository
from app_infra.postgres.task.task_repository import ClaimResult, PostgresTaskRepository
from app_infra.postgres.test_database_guard import require_isolated_database
from app_infra.postgres.workspace_purge_enqueuer import PostgresWorkspacePurgeEnqueuer
from app_infra.postgres.workspace_purge_repository import (
    PostgresWorkspacePurgeRepository,
)
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from task_runtime.registry import HandlerRegistry, HandlerSpec
from task_runtime.runtime import WorkerHost

from workers.maintenance.task_handlers.lifecycle_purge import LifecyclePurgeHandler

DATABASE_URL = "postgresql+psycopg://torch@localhost:5432/dom_workspace_lifecycle_test"


class _TaskScopedRepository(PostgresTaskRepository):
    def __init__(self, session: AsyncSession, task_id: UUID) -> None:
        super().__init__(session)
        self._task_id = task_id

    async def claim_next(
        self, worker_id: str, lease_seconds: int
    ) -> ClaimResult | None:
        return await self.claim(self._task_id, worker_id, lease_seconds)


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
        # Keep every case on its own outer transaction, including session commits.
        transaction = await connection.begin()
        factory = async_sessionmaker(
            bind=connection,
            expire_on_commit=False,
            class_=AsyncSession,
            join_transaction_mode="create_savepoint",
        )
        try:
            async with factory() as session:
                try:
                    yield session
                finally:
                    await session.rollback()
        finally:
            if transaction.is_active:
                await transaction.rollback()


def _cleanup(session: AsyncSession) -> WorkspaceMembershipCleanupPort:
    return PostgresWorkspaceMembershipRepository(session)


async def _workspace(
    session: AsyncSession, *, status: str, eligible_at: datetime
) -> UUID:
    workspace_id = uuid4()
    account_id = await session.scalar(
        text(
            "SELECT a.account_id FROM auth.accounts a WHERE NOT EXISTS "
            "(SELECT 1 FROM core.workspace_members wm "
            "WHERE wm.account_id=a.account_id) "
            "LIMIT 1"
        )
    )
    if account_id is None:
        account_id = uuid4()
        await session.execute(
            text(
                "INSERT INTO auth.accounts (account_id,email,password_hash,status,"
                "created_at,updated_at) VALUES (:id,:email,'x','Active',now(),now())"
            ),
            {"id": account_id, "email": f"purge-{account_id}@example.test"},
        )
    await session.execute(
        text(
            "INSERT INTO core.workspaces (workspace_id,name,status,created_by,"
            "created_at,updated_at,deletion_requested_at,purge_eligible_at) "
            "VALUES (:id,:name,:status,:owner,now(),now(),:eligible,:eligible)"
        ),
        {
            "id": workspace_id,
            "name": f"purge-{workspace_id}",
            "status": status,
            "owner": account_id,
            "eligible": eligible_at,
        },
    )
    return workspace_id


@pytest.mark.asyncio
async def test_only_expired_eligible_workspaces_selected(
    db_session: AsyncSession,
) -> None:
    now = datetime.now(UTC)
    expired = await _workspace(
        db_session, status="DeletionPending", eligible_at=now - timedelta(seconds=1)
    )
    future = await _workspace(
        db_session, status="DeletionPending", eligible_at=now + timedelta(days=1)
    )
    active = await _workspace(
        db_session, status="Active", eligible_at=now - timedelta(days=1)
    )
    repo = PostgresWorkspacePurgeRepository(db_session, _cleanup(db_session))
    candidates = await repo.candidates_before(now, 100)
    ids = {item.workspace_id for item in candidates}
    assert expired in ids
    assert future not in ids
    assert active not in ids


@pytest.mark.asyncio
async def test_enqueuer_twice_persists_one_deterministic_task(
    db_session: AsyncSession,
) -> None:
    now = datetime.now(UTC)
    workspace_id = await _workspace(
        db_session, status="DeletionPending", eligible_at=now - timedelta(seconds=1)
    )
    purge_repo = PostgresWorkspacePurgeRepository(db_session, _cleanup(db_session))
    enqueuer = PostgresWorkspacePurgeEnqueuer(db_session, purge_repo)
    await enqueuer.enqueue(now, 20)
    await enqueuer.enqueue(now, 20)
    rows = await db_session.execute(
        text("SELECT task_id,input_ref FROM work.tasks WHERE input_ref=:id"),
        {"id": str(workspace_id)},
    )
    task_rows = rows.mappings().all()
    assert len(task_rows) == 1
    assert task_rows[0]["input_ref"] == str(workspace_id)


@pytest.mark.asyncio
async def test_real_task_worker_handler_purges_and_records_effect(
    db_session: AsyncSession,
) -> None:
    now = datetime.now(UTC)
    workspace_id = await _workspace(
        db_session, status="DeletionPending", eligible_at=now - timedelta(seconds=1)
    )
    purge_repo = PostgresWorkspacePurgeRepository(db_session, _cleanup(db_session))
    await PostgresWorkspacePurgeEnqueuer(db_session, purge_repo).enqueue(now, 20)
    task_id = await db_session.scalar(
        text("SELECT task_id FROM work.tasks WHERE input_ref=:id"),
        {"id": str(workspace_id)},
    )
    assert task_id is not None
    task_repo = _TaskScopedRepository(db_session, task_id)
    effects = PostgresTaskEffectRepository(db_session)
    handler = LifecyclePurgeHandler(
        PurgeWorkspace(purge_repo, _cleanup(db_session)), effects
    )
    registry = HandlerRegistry()
    registry.register(HandlerSpec("lifecycle.purge.workspace", handler))
    worker = WorkerHost(
        task_repo, registry, worker_id="purge-bdd", heartbeat_seconds=60
    )
    assert await worker.run_once()
    assert (
        await db_session.scalar(
            text("SELECT count(*) FROM core.workspaces WHERE workspace_id=:id"),
            {"id": workspace_id},
        )
        == 0
    )
    assert (
        await db_session.scalar(
            text("SELECT count(*) FROM work.task_effects WHERE task_id=:id"),
            {"id": task_id},
        )
        == 1
    )


@pytest.mark.asyncio
async def test_concurrent_repeated_purge_is_idempotent(
    db_session: AsyncSession,
) -> None:
    now = datetime.now(UTC)
    workspace_id = await _workspace(
        db_session, status="DeletionPending", eligible_at=now - timedelta(seconds=1)
    )
    repository = PostgresWorkspacePurgeRepository(db_session, _cleanup(db_session))
    first = await repository.purge_workspace(workspace_id)
    second = await repository.purge_workspace(workspace_id)
    assert first.disposition.value == "Purged"
    assert second.disposition.value == "AlreadyPurged"
