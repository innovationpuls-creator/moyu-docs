from __future__ import annotations

import os
from pathlib import Path
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
from alembic import command
from alembic.config import Config
from app_core.operations.task import CreateTask
from app_infra.postgres.engine import engine
from app_infra.postgres.project_repository import PostgresProjectRepository
from app_infra.postgres.resource.checkpoint_repository import (
    PostgresCheckpointRepository,
)
from app_infra.postgres.resource.journal_repository import PostgresJournalRepository
from app_infra.postgres.resource.resource_checkpoint_enqueuer import (
    PostgresResourceCheckpointEnqueuer,
)
from app_infra.postgres.resource.resource_repository import PostgresResourceRepository
from app_infra.postgres.search_repository import PostgresSearchRepository
from app_infra.postgres.task.effect_repository import PostgresTaskEffectRepository
from app_infra.postgres.task.task_repository import ClaimResult, PostgresTaskRepository
from app_infra.postgres.test_database_guard import require_isolated_database
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from task_runtime.registry import HandlerRegistry, HandlerSpec
from task_runtime.runtime import WorkerHost

from workers.maintenance.task_handlers.resource_checkpoint import (
    ResourceCheckpointHandler,
)

DATABASE_URL = "postgresql+psycopg://torch@localhost:5432/dom_workspace_lifecycle_test"
_ACCOUNT_IDS = (
    "SELECT account_id FROM auth.accounts WHERE primary_email LIKE 'checkpoint-%@test'"
)
_WORKSPACE_IDS = (
    f"SELECT workspace_id FROM core.workspaces WHERE created_by IN ({_ACCOUNT_IDS})"
)
_PROJECT_IDS = (
    f"SELECT project_id FROM core.projects WHERE workspace_id IN ({_WORKSPACE_IDS})"
)
_RESOURCE_IDS = (
    f"SELECT resource_id FROM core.resources WHERE project_id IN ({_PROJECT_IDS})"
)
_CHECKPOINT_TASK_IDS = (
    "SELECT task_id FROM work.tasks WHERE task_type='resource.checkpoint' "
    f"AND input_ref IN (SELECT resource_id::text FROM ({_RESOURCE_IDS}) AS resources)"
)


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


@pytest_asyncio.fixture(autouse=True)
async def clean_tables() -> None:
    connection = await engine.connect()
    try:
        session = AsyncSession(connection)
        async with session.begin():
            for table in ("work.task_effects", "work.task_attempts"):
                await session.execute(
                    text(
                        f"DELETE FROM {table} WHERE task_id IN ({_CHECKPOINT_TASK_IDS})"
                    )
                )
            await session.execute(
                text(
                    f"DELETE FROM work.tasks WHERE task_id IN ({_CHECKPOINT_TASK_IDS})"
                )
            )
            for table in (
                "collab.resource_search_index",
                "collab.resource_assets",
                "collab.ai_changesets",
                "collab.resource_named_versions",
                "collab.resource_comments",
                "collab.comment_threads",
                "collab.resource_ownership",
                "collab.resource_checkpoints",
                "collab.resource_update_journal",
            ):
                await session.execute(
                    text(f"DELETE FROM {table} WHERE resource_id IN ({_RESOURCE_IDS})")
                )
            await session.execute(
                text(
                    "DELETE FROM core.invitations WHERE "
                    f"workspace_id IN ({_WORKSPACE_IDS}) OR "
                    f"project_id IN ({_PROJECT_IDS}) OR "
                    f"resource_id IN ({_RESOURCE_IDS})"
                )
            )
            for table in ("core.resource_permissions", "core.share_links"):
                await session.execute(
                    text(f"DELETE FROM {table} WHERE resource_id IN ({_RESOURCE_IDS})")
                )
            await session.execute(
                text(
                    "DELETE FROM core.workspace_members "
                    f"WHERE workspace_id IN ({_WORKSPACE_IDS})"
                )
            )
            await session.execute(
                text(
                    "DELETE FROM core.project_members "
                    f"WHERE project_id IN ({_PROJECT_IDS})"
                )
            )
            await session.execute(
                text(
                    f"DELETE FROM core.resources WHERE resource_id IN ({_RESOURCE_IDS})"
                )
            )
            await session.execute(
                text(f"DELETE FROM core.folders WHERE project_id IN ({_PROJECT_IDS})")
            )
            await session.execute(
                text(f"DELETE FROM core.projects WHERE project_id IN ({_PROJECT_IDS})")
            )
            await session.execute(
                text(
                    "DELETE FROM core.workspaces "
                    f"WHERE workspace_id IN ({_WORKSPACE_IDS})"
                )
            )
            await session.execute(
                text(f"DELETE FROM auth.accounts WHERE account_id IN ({_ACCOUNT_IDS})")
            )
        await session.close()
    finally:
        await connection.close()


async def _seed_project(session: AsyncSession) -> str:
    account_id = uuid4()
    workspace_id = uuid4()
    project_id = uuid4()
    await session.execute(
        text(
            "INSERT INTO auth.accounts "
            "(account_id,status,primary_email,normalized_email) "
            "VALUES (:a,'Active',:e,:e)"
        ),
        {"a": account_id, "e": f"checkpoint-{account_id}@test"},
    )
    await session.execute(
        text(
            "INSERT INTO core.workspaces "
            "(workspace_id,name,status,created_by,created_at,updated_at) "
            "VALUES (:w,'RC WS','Active',:a,now(),now())"
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
    return str(project_id), str(workspace_id)


@pytest.mark.asyncio
async def test_checkpoint_consumer_end_to_end() -> None:
    connection = await engine.connect()
    session = AsyncSession(connection)
    try:
        async with session.begin():
            project_id, workspace_id = await _seed_project(session)
            repo = PostgresResourceRepository(session)
            resource = await repo.create(
                project_id=project_id,
                resource_type="document",
                name="Doc",
                normalized_name="doc",
            )
            journal = PostgresJournalRepository(session)
            for seq in range(1, 5):
                await journal.append_op(resource.resource_id, seq, 7, b"op", f"h{seq}")
        create = CreateTask(PostgresTaskRepository(session))
        enqueued = await PostgresResourceCheckpointEnqueuer(session, create).enqueue(
            threshold=3
        )
        assert enqueued >= 1
        task_id = await session.scalar(
            text(
                "SELECT task_id FROM work.tasks "
                "WHERE task_type='resource.checkpoint' AND input_ref=:id "
                "ORDER BY created_at DESC LIMIT 1"
            ),
            {"id": str(resource.resource_id)},
        )
        assert task_id is not None
        effects = PostgresTaskEffectRepository(session)
        journal = PostgresJournalRepository(session)
        handler = ResourceCheckpointHandler(
            journal,
            PostgresCheckpointRepository(session),
            effects,
            materialize=lambda rid, base: {
                "resourceId": str(rid),
                "baseJournalSeq": base,
                "text": "版本四的错误信封设计",
            },
            search_index=PostgresSearchRepository(session),
            resources=PostgresResourceRepository(session),
            projects=PostgresProjectRepository(session),
        )
        registry = HandlerRegistry()
        registry.register(HandlerSpec("resource.checkpoint", handler))
        worker = WorkerHost(
            _TaskScopedRepository(session, task_id),
            registry,
            worker_id="rc-bdd",
            heartbeat_seconds=60,
        )
        assert await worker.run_once()
        await session.commit()
        async with session.begin():
            checkpoint_count = await session.scalar(
                text(
                    "SELECT count(*) FROM collab.resource_checkpoints "
                    "WHERE resource_id=:id"
                ),
                {"id": resource.resource_id},
            )
            effect_count = await session.scalar(
                text(
                    "SELECT count(*) FROM work.task_effects "
                    "WHERE effect_key LIKE 'resource.checkpoint:%'"
                )
            )
        assert checkpoint_count == 1
        assert effect_count == 1
        # Search index populated by the checkpoint consumer (arch 11).
        async with session.begin():
            probe = (
                (
                    await session.execute(
                        text(
                            "SELECT workspace_id, name, searchable_text, lifecycle "
                            "FROM collab.resource_search_index "
                            "WHERE resource_id=:id"
                        ),
                        {"id": resource.resource_id},
                    )
                )
                .mappings()
                .all()
            )
            print("PROBE", [dict(r) for r in probe])
        hits = await PostgresSearchRepository(session).search_workspace(
            workspace_id, "错误信封"
        )
        for h in hits:
            print("HIT", h.name, h.score)
        assert any(h.name == "Doc" for h in hits)
    finally:
        await session.close()
        await connection.close()
