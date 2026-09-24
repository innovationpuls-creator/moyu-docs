from __future__ import annotations

import os
from pathlib import Path
from uuid import uuid4

import pytest
import pytest_asyncio
from alembic import command
from alembic.config import Config
from app_infra.postgres.engine import engine
from app_infra.postgres.test_database_guard import require_isolated_database
from sqlalchemy import inspect, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


@pytest_asyncio.fixture(scope="module", autouse=True)
async def migrated_database() -> None:
    database_url = require_isolated_database(os.environ["DATABASE_URL"])
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


@pytest.mark.asyncio
async def test_lifecycle_schema_has_workspace_project_and_folder_tables() -> None:
    async with engine.connect() as connection:
        table_names = await connection.run_sync(
            lambda sync_connection: inspect(sync_connection).get_table_names(
                schema="core"
            )
        )
    assert {"workspaces", "projects", "folders"} <= set(table_names)


@pytest.mark.asyncio
async def test_workspace_repository_rejects_existing_workspace_id(
    db_session: AsyncSession,
) -> None:
    from app_core.workspace.application.use_cases import Workspace
    from app_core.workspace.domain.name import WorkspaceName
    from app_infra.postgres.workspace_repository import PostgresWorkspaceRepository

    repository = PostgresWorkspaceRepository(db_session)
    workspace_id, creator_id = uuid4(), uuid4()
    workspace = Workspace(workspace_id, WorkspaceName("Original"), creator_id)

    await db_session.execute(
        text(
            "INSERT INTO auth.accounts "
            "(account_id, status, primary_email, normalized_email) "
            "VALUES (:account_id, 'Active', :email, :normalized_email)"
        ),
        {
            "account_id": creator_id,
            "email": f"{creator_id}@example.test",
            "normalized_email": f"{creator_id}@example.test",
        },
    )
    await repository.save(workspace)

    with pytest.raises(IntegrityError):
        async with db_session.begin_nested():
            await repository.save(
                Workspace(workspace_id, WorkspaceName("Unintended rename"), uuid4())
            )

    found = await repository.find_by_id(workspace_id)
    assert found == workspace


@pytest.mark.asyncio
async def test_workspace_repository_saves_and_finds_metadata(
    db_session: AsyncSession,
) -> None:
    from app_core.workspace.application.use_cases import Workspace
    from app_core.workspace.domain.name import WorkspaceName
    from app_infra.postgres.workspace_repository import PostgresWorkspaceRepository

    repository = PostgresWorkspaceRepository(db_session)
    workspace_id = uuid4()
    creator_id = uuid4()
    workspace = Workspace(workspace_id, WorkspaceName("  Cafe\u0301  "), creator_id)

    await db_session.execute(
        text(
            "INSERT INTO auth.accounts "
            "(account_id, status, primary_email, normalized_email) "
            "VALUES (:account_id, 'Active', :email, :normalized_email)"
        ),
        {
            "account_id": creator_id,
            "email": f"{creator_id}@example.test",
            "normalized_email": f"{creator_id}@example.test",
        },
    )
    await repository.save(workspace)
    found = await repository.find_by_id(workspace_id)

    assert found == workspace
    stored = await db_session.execute(
        text(
            "SELECT name, created_by, created_at FROM core.workspaces "
            "WHERE workspace_id = :workspace_id"
        ),
        {"workspace_id": workspace.workspace_id},
    )
    stored_row = stored.one()
    assert stored_row.name == "  Cafe\u0301  "
    assert stored_row.created_by == creator_id
    assert stored_row.created_at == workspace.created_at
