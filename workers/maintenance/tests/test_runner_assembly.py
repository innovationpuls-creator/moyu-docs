"""Arch 25: the maintenance runner assembles consumers over the real chain."""

from __future__ import annotations

from collections.abc import AsyncGenerator
from pathlib import Path
from uuid import uuid4

import pytest
import pytest_asyncio
from alembic import command
from alembic.config import Config
from app_core.operations.task import CreateTask
from app_infra.postgres.resource.journal_repository import PostgresJournalRepository
from app_infra.postgres.resource.resource_repository import (
    PostgresResourceRepository,
)
from app_infra.postgres.resource_ownership_repository import (
    PostgresResourceOwnershipRepository,
)
from app_infra.postgres.task.task_repository import PostgresTaskRepository
from app_infra.postgres.test_database_guard import require_isolated_database
from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from task_runtime.runtime import HandlerContext

from workers.maintenance.main import build_registry, sweep
from workers.maintenance.task_handlers.history_restore import (
    TASK_TYPE as HISTORY_RESTORE_TASK_TYPE,
)
from workers.maintenance.task_handlers.history_restore import (
    input_ref as history_restore_input_ref,
)

DATABASE_URL = "postgresql+psycopg://torch@localhost:5432/dom_workspace_lifecycle_test"


@pytest_asyncio.fixture(scope="module", autouse=True)
async def migrated_database() -> AsyncGenerator[AsyncEngine, None]:
    database_url = require_isolated_database(DATABASE_URL)
    config = Config(str(Path("migrations/postgres/alembic.ini")))
    config.set_main_option("sqlalchemy.url", database_url)
    command.upgrade(config, "head")
    test_engine = create_async_engine(database_url, echo=False)
    try:
        yield test_engine
    finally:
        await test_engine.dispose()


@pytest_asyncio.fixture
async def db_session(
    migrated_database: AsyncEngine,
) -> AsyncGenerator[AsyncSession, None]:
    conn = await migrated_database.connect()
    tx = await conn.begin()
    factory = async_sessionmaker(bind=conn, expire_on_commit=False, class_=AsyncSession)
    session = factory()
    try:
        yield session
    finally:
        await session.close()
        await tx.rollback()
        await conn.close()


@pytest.mark.asyncio
async def test_runner_assembles_consumers_and_sweeps(db_session: AsyncSession) -> None:
    """The runner registers History Restore and executes it through real repos."""
    from app_core.resource.domain import ResourceContent, ResourceContentMutation

    class _Content:
        def __init__(self) -> None:
            self.replacements: list[dict] = []

        async def read(self, _resource_id, *, at_journal_seq=None):
            return ResourceContent({"text": "before"}, at_journal_seq or 2)

        async def replace(self, resource_id, snapshot, **kwargs):
            self.replacements.append(
                {"resource_id": resource_id, "snapshot": snapshot, **kwargs}
            )
            return ResourceContentMutation(3)

    content = _Content()
    registry = build_registry(db_session, resource_content=content)
    for task_type in (
        "resource.checkpoint",
        "resource.purge",
        "lifecycle.purge",
        HISTORY_RESTORE_TASK_TYPE,
    ):
        assert task_type in registry, task_type
    assert "webhook.deliver" in registry
    async with db_session.begin():
        account_id = uuid4()
        workspace_id = uuid4()
        project_id = uuid4()
        await db_session.execute(
            text(
                "INSERT INTO auth.accounts "
                "(account_id,status,primary_email,normalized_email) "
                "VALUES (:a,'Active',:e,:e)"
            ),
            {"a": account_id, "e": f"runa-{account_id}@test"},
        )
        await db_session.execute(
            text(
                "INSERT INTO core.workspaces "
                "(workspace_id,name,status,created_by,created_at,updated_at) "
                "VALUES (:w,'W','Active',:a,now(),now())"
            ),
            {"w": workspace_id, "a": account_id},
        )
        await db_session.execute(
            text(
                "INSERT INTO core.workspace_members "
                "(workspace_id,account_id,membership_kind) "
                "VALUES (:w,:a,'Owner')"
            ),
            {"w": workspace_id, "a": account_id},
        )
        await db_session.execute(
            text(
                "INSERT INTO core.projects "
                "(project_id,workspace_id,name,normalized_name,lifecycle,"
                "created_by,created_at,updated_at) "
                "VALUES (:p,:w,'P','p','Active',:a,now(),now())"
            ),
            {"p": project_id, "w": workspace_id, "a": account_id},
        )
        resource = await PostgresResourceRepository(db_session).create(
            project_id=project_id,
            resource_type="document",
            name="Doc",
            normalized_name="doc",
        )
        await PostgresResourceOwnershipRepository(db_session).grant(
            resource.resource_id, account_id
        )
        journal = PostgresJournalRepository(db_session)
        await journal.append_op(resource.resource_id, 1, 1, b'{"text":"before"}', "h1")
        await journal.append_op(resource.resource_id, 2, 1, b'{"text":"after"}', "h2")

        task_repo = PostgresTaskRepository(db_session)
        task = await CreateTask(task_repo).execute(
            HISTORY_RESTORE_TASK_TYPE,
            input_ref=history_restore_input_ref(resource.resource_id, 1),
            actor_account_id=account_id,
            resource_id=resource.resource_id,
        )
        claim = await task_repo.claim(task.task_id, "history-restore-test", 30)
        assert claim is not None
        claimed_task = await task_repo.get(task.task_id)
        assert claimed_task is not None
        context = HandlerContext(
            claimed_task,
            claim.attempt_id,
            claim.execution_epoch,
            task_repo,
        )
        handler = registry.resolve(
            HISTORY_RESTORE_TASK_TYPE, claimed_task.schema_version
        ).handler
        await handler.execute(context)
        await task_repo.finish(
            task.task_id, claim.attempt_id, claim.execution_epoch, True
        )
        assert content.replacements == [
            {
                "resource_id": resource.resource_id,
                "snapshot": {"text": "before"},
                "operation_id": task.task_id,
                "created_by": account_id,
                "reason": "history-restore",
                "restore_target_seq": 1,
            }
        ]
        completed = await task_repo.get(task.task_id)
        assert completed is not None
        assert completed.state.value == "Succeeded"
    enqueued = await sweep(db_session)
    assert enqueued >= 1  # global sweep; other tests may also qualify


@pytest.mark.asyncio
async def test_daemon_ticks_bound(migrated_database: AsyncEngine) -> None:
    """The daemon loop performs a bounded number of claim cycles (max_ticks)."""
    from workers.maintenance.main import run_daemon

    runner_factory = async_sessionmaker(
        bind=migrated_database, expire_on_commit=False, class_=AsyncSession
    )
    worked = await run_daemon(runner_factory, max_ticks=2)
    assert worked <= 2
