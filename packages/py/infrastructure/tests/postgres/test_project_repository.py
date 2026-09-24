from __future__ import annotations

import os
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest
import pytest_asyncio
from alembic import command
from alembic.config import Config
from app_infra.postgres.engine import engine
from app_infra.postgres.test_database_guard import require_isolated_database
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

DATABASE_URL = "postgresql+psycopg://torch@localhost:5432/dom_workspace_lifecycle_test"


@pytest_asyncio.fixture(scope="module", autouse=True)
async def migrated_database() -> None:
    database_url = require_isolated_database(os.environ["DATABASE_URL"])
    if database_url != DATABASE_URL:
        raise ValueError("Unexpected database URL")
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


async def _workspace(session: AsyncSession):
    account_id, workspace_id = uuid4(), uuid4()
    await session.execute(
        text(
            "INSERT INTO auth.accounts "
            "(account_id,status,primary_email,normalized_email) "
            "VALUES (:id,'Active',:email,:email)"
        ),
        {"id": account_id, "email": f"{account_id}@example.test"},
    )
    await session.execute(
        text(
            "INSERT INTO core.workspaces (workspace_id,name,created_by) "
            "VALUES (:id,'Task 6b',:creator)"
        ),
        {"id": workspace_id, "creator": account_id},
    )
    return workspace_id, account_id


@pytest.mark.asyncio
async def test_project_repository_persists_and_rehydrates_columns(db_session):
    from app_core.workspace.domain.project import (
        Project,
        ProjectExtendedLifecycle,
        ProjectName,
    )
    from app_infra.postgres.project_repository import PostgresProjectRepository

    workspace_id, creator_id = await _workspace(db_session)
    repository = PostgresProjectRepository(db_session)
    now = datetime.now(UTC)
    project = Project(
        uuid4(),
        workspace_id,
        ProjectName("  Café  "),
        created_by=creator_id,
        created_at=now,
        updated_at=now,
    )
    await repository.save(project)
    loaded = await repository.find_by_id(project.project_id)
    assert loaded == project
    row = (
        await db_session.execute(
            text(
                "SELECT normalized_name,lifecycle,created_by,created_at,updated_at "
                "FROM core.projects WHERE project_id=:id"
            ),
            {"id": project.project_id},
        )
    ).one()
    assert row.normalized_name == "café"
    assert row.lifecycle == ProjectExtendedLifecycle.ACTIVE.value
    assert row.created_by == creator_id
    assert row.created_at == project.created_at
    assert row.updated_at == project.updated_at


@pytest.mark.asyncio
async def test_project_name_reservations_include_trashed_and_purged_rows(db_session):
    from app_core.workspace.domain.project import (
        Project,
        ProjectExtendedLifecycle,
        ProjectName,
    )
    from app_infra.postgres.project_repository import PostgresProjectRepository

    workspace_id, creator_id = await _workspace(db_session)
    repository = PostgresProjectRepository(db_session)
    for state in (ProjectExtendedLifecycle.TRASHED, ProjectExtendedLifecycle.PURGED):
        project = Project(
            uuid4(), workspace_id, ProjectName(state.value), state, creator_id
        )
        await repository.save(project)
    reservations = await repository.list_name_reservations(workspace_id)
    assert {item.lifecycle for item in reservations} == {
        ProjectExtendedLifecycle.TRASHED,
        ProjectExtendedLifecycle.PURGED,
    }


@pytest.mark.asyncio
async def test_project_name_unique_constraint_reserves_trashed_name(db_session):
    from app_core.workspace.domain.project import (
        Project,
        ProjectExtendedLifecycle,
        ProjectName,
    )
    from app_infra.postgres.project_repository import PostgresProjectRepository

    workspace_id, creator_id = await _workspace(db_session)
    repository = PostgresProjectRepository(db_session)
    await repository.save(
        Project(
            uuid4(),
            workspace_id,
            ProjectName("Reserved"),
            ProjectExtendedLifecycle.TRASHED,
            creator_id,
        )
    )
    with pytest.raises(IntegrityError):
        async with db_session.begin_nested():
            await repository.save(
                Project(
                    uuid4(),
                    workspace_id,
                    ProjectName(" reserved "),
                    created_by=creator_id,
                )
            )


def test_project_state_enum_contains_persisted_lifecycle_values():
    from app_core.workspace.domain.project import ProjectExtendedLifecycle

    assert {item.value for item in ProjectExtendedLifecycle} == {
        "Active",
        "Archived",
        "Trashed",
        "Purging",
        "Purged",
    }
