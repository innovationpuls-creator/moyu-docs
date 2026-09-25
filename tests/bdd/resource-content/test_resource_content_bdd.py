"""Resource Content BDD — real chain evidence (no HTTP): ownership grant ->
CreateResource -> AppendJournalOp -> Checkpoint -> Restore; plus the durable
checkpoint Task consumer. Module guard: isolated dom_workspace_lifecycle_test.
"""

from __future__ import annotations

import os
from pathlib import Path
from uuid import uuid4

import pytest
import pytest_asyncio
from alembic import command
from alembic.config import Config
from app_core.operations.task import CreateTask
from app_core.resource.application import (
    AppendJournalOp,
    CheckpointResource,
    CreateResource,
    RestoreAtRevision,
)
from app_core.resource.domain import ResourceNameConflictError
from app_infra.postgres.engine import engine
from app_infra.postgres.resource.checkpoint_repository import (
    PostgresCheckpointRepository,
)
from app_infra.postgres.resource.journal_repository import PostgresJournalRepository
from app_infra.postgres.resource.resource_checkpoint_enqueuer import (
    PostgresResourceCheckpointEnqueuer,
)
from app_infra.postgres.resource.resource_repository import PostgresResourceRepository
from app_infra.postgres.resource_ownership_repository import (
    PostgresResourceOwnershipRepository,
)
from app_infra.postgres.task.effect_repository import PostgresTaskEffectRepository
from app_infra.postgres.task.task_repository import PostgresTaskRepository
from app_infra.postgres.test_database_guard import require_isolated_database
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from task_runtime.registry import HandlerRegistry, HandlerSpec
from task_runtime.runtime import WorkerHost

from workers.maintenance.task_handlers.resource_checkpoint import (
    ResourceCheckpointHandler,
)

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


async def _seed_owner_project(session: AsyncSession) -> tuple[str, str, str]:
    """Workspace (Owner) + Project; returns (account_id, project_id, workspace_id)."""
    account_id = uuid4()
    workspace_id = uuid4()
    project_id = uuid4()
    await session.execute(
        text(
            "INSERT INTO auth.accounts "
            "(account_id,status,primary_email,normalized_email) "
            "VALUES (:a,'Active',:e,:e)"
        ),
        {"a": account_id, "e": f"bdd-{account_id}@test"},
    )
    await session.execute(
        text(
            "INSERT INTO core.workspaces "
            "(workspace_id,name,status,created_by,created_at,updated_at) "
            "VALUES (:w,'BDD WS','Active',:a,now(),now())"
        ),
        {"w": workspace_id, "a": account_id},
    )
    await session.execute(
        text(
            "INSERT INTO core.workspace_members "
            "(workspace_id,account_id,membership_kind) VALUES (:w,:a,'Owner')"
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
    return str(account_id), str(project_id), str(workspace_id)


def _resources(session: AsyncSession) -> tuple:
    repo = PostgresResourceRepository(session)
    ownership = PostgresResourceOwnershipRepository(session)
    journal = PostgresJournalRepository(session)
    checkpoints = PostgresCheckpointRepository(session)
    return repo, ownership, journal, checkpoints


@pytest.mark.asyncio
async def test_create_requires_ownership_and_sibling_conflict(
    db_session: AsyncSession,
) -> None:
    async with db_session.begin():
        account_id, project_id, _ = await _seed_owner_project(db_session)
    repo, ownership, _, _ = _resources(db_session)
    create = CreateResource(repo, ownership)
    async with db_session.begin():
        resource = await create.execute(
            account_id, project_id=project_id, resource_type="document", name="Note"
        )
        # sibling (casefold-equal) must be rejected for the OWNER
        with pytest.raises(ResourceNameConflictError):
            await create.execute(
                account_id,
                project_id=project_id,
                resource_type="document",
                name="note",
            )
        # un-owned actor denied BEFORE any name check
        other = uuid4()
        await db_session.execute(
            text(
                "INSERT INTO auth.accounts "
                "(account_id,status,primary_email,normalized_email) "
                "VALUES (:a,'Active',:e,:e)"
            ),
            {"a": other, "e": f"bdd-{other}@test"},
        )
        with pytest.raises(Exception) as exc:
            await create.execute(
                other,
                project_id=project_id,
                resource_type="document",
                name="Unique",
            )
        assert "permission" in str(exc.value)
    assert resource.resource_type == "document"
    row = await repo.get(resource.resource_id)
    assert row is not None and row.lifecycle == "Active"


@pytest.mark.asyncio
async def test_journal_checkpoint_restore_chain(db_session: AsyncSession) -> None:
    async with db_session.begin():
        account_id, project_id, _ = await _seed_owner_project(db_session)
    repo, ownership, journal, checkpoints = _resources(db_session)
    create = CreateResource(repo, ownership)
    async with db_session.begin():
        resource = await create.execute(
            account_id, project_id=project_id, resource_type="markdown", name="Doc"
        )
        await ownership.grant(resource.resource_id, account_id)
    append = AppendJournalOp(repo, journal, ownership)
    async with db_session.begin():
        for i in range(1, 4):
            await append.execute(
                account_id,
                resource.resource_id,
                b"op" + str(i).encode(),
                ownership_epoch=1,
            )
        checkpoint = await CheckpointResource(journal, checkpoints).execute(
            resource.resource_id, {"v": "snap"}
        )
    assert checkpoint.base_journal_seq == 3
    restore = RestoreAtRevision(
        journal, checkpoints, apply=lambda state, op: {**state, "seq": op.journal_seq}
    )
    async with db_session.begin():
        state = await restore.execute(resource.resource_id, 3)
    assert state["v"] == "snap"


@pytest.mark.asyncio
async def test_checkpoint_task_consumer_records_fenced_effect(
    db_session: AsyncSession,
) -> None:
    async with db_session.begin():
        account_id, project_id, _ = await _seed_owner_project(db_session)
    repo, ownership, journal, checkpoints = _resources(db_session)
    create = CreateResource(repo, ownership)
    async with db_session.begin():
        resource = await create.execute(
            account_id, project_id=project_id, resource_type="text", name="T"
        )
        await ownership.grant(resource.resource_id, account_id)
    append = AppendJournalOp(repo, journal, ownership)
    async with db_session.begin():
        for i in range(1, 5):
            await append.execute(
                account_id,
                resource.resource_id,
                b"x",
                ownership_epoch=1,
            )
    enqueued = await PostgresResourceCheckpointEnqueuer(
        db_session, CreateTask(PostgresTaskRepository(db_session))
    ).enqueue(threshold=3)
    assert enqueued == 1
    await db_session.commit()
    task_id = await db_session.scalar(
        text("SELECT task_id FROM work.tasks WHERE task_type='resource.checkpoint'")
    )
    assert task_id is not None
    handler = ResourceCheckpointHandler(
        journal, checkpoints, PostgresTaskEffectRepository(db_session)
    )
    registry = HandlerRegistry()
    registry.register(HandlerSpec("resource.checkpoint", handler))
    worker = WorkerHost(
        PostgresTaskRepository(db_session),
        registry,
        worker_id="rc-bdd",
        heartbeat_seconds=60,
    )
    assert await worker.run_once()
    await db_session.commit()
    checkpoint_count = await db_session.scalar(
        text("SELECT count(*) FROM collab.resource_checkpoints WHERE resource_id=:id"),
        {"id": resource.resource_id},
    )
    effect_count = await db_session.scalar(
        text(
            "SELECT count(*) FROM work.task_effects "
            "WHERE effect_key LIKE 'resource.checkpoint:%'"
        )
    )
    assert checkpoint_count == 1
    assert effect_count == 1
