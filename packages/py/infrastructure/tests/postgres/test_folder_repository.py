from __future__ import annotations

import asyncio
import os
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest
import pytest_asyncio
from alembic import command
from alembic.config import Config
from app_core.common.exceptions import ConflictError
from app_infra.postgres.engine import engine
from app_infra.postgres.test_database_guard import require_isolated_database
from sqlalchemy import text
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


async def _workspace_and_project(session: AsyncSession):
    account_id, workspace_id, project_id = uuid4(), uuid4(), uuid4()
    await session.execute(
        text(
            "INSERT INTO auth.accounts (account_id,status,primary_email,"
            "normalized_email) "
            "VALUES (:id,'Active',:email,:email)"
        ),
        {"id": account_id, "email": f"{account_id}@example.test"},
    )
    await session.execute(
        text(
            "INSERT INTO core.workspaces (workspace_id,name,created_by) "
            "VALUES (:id,'Folder tests',:creator)"
        ),
        {"id": workspace_id, "creator": account_id},
    )
    await session.execute(
        text(
            "INSERT INTO core.projects "
            "(project_id,workspace_id,name,normalized_name,created_by) "
            "VALUES (:id,:workspace,'Project','project',:creator)"
        ),
        {"id": project_id, "workspace": workspace_id, "creator": account_id},
    )
    await session.execute(
        text(
            "INSERT INTO core.workspace_members "
            "(workspace_id,account_id,membership_kind) "
            "VALUES (:workspace_id,:account_id,'Owner')"
        ),
        {"workspace_id": workspace_id, "account_id": account_id},
    )
    return workspace_id, account_id, project_id


@pytest.mark.asyncio
async def test_folder_repository_persists_and_rehydrates_columns(db_session):
    from app_core.workspace.domain.folder import Folder, FolderName
    from app_infra.postgres.folder_repository import PostgresFolderRepository

    _, _, project_id = await _workspace_and_project(db_session)
    repository = PostgresFolderRepository(db_session)
    now = datetime.now(UTC)
    folder = Folder(
        uuid4(),
        project_id,
        None,
        FolderName("Root"),
        created_at=now,
        updated_at=now,
    )
    await repository.save(folder)
    assert await repository.find_by_id(folder.folder_id) == folder
    row = (
        await db_session.execute(
            text(
                "SELECT normalized_name,lifecycle,created_at,updated_at "
                "FROM core.folders "
                "WHERE folder_id=:id"
            ),
            {"id": folder.folder_id},
        )
    ).one()
    assert row.normalized_name == "root"
    assert row.lifecycle == "Active"
    assert row.created_at == folder.created_at
    assert row.updated_at == folder.updated_at


@pytest.mark.asyncio
async def test_folder_parent_from_another_project_is_rejected_before_write(db_session):
    from app_core.workspace.domain.folder import Folder, FolderName
    from app_infra.postgres.folder_repository import PostgresFolderRepository

    _, _, project_a = await _workspace_and_project(db_session)
    _, _, project_b = await _workspace_and_project(db_session)
    repository = PostgresFolderRepository(db_session)
    parent = Folder(
        uuid4(),
        project_a,
        None,
        FolderName("Parent"),
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    await repository.save(parent)
    with pytest.raises(ConflictError):
        await repository.save(
            Folder(
                uuid4(),
                project_b,
                parent.folder_id,
                FolderName("Child"),
                created_at=datetime.now(UTC),
                updated_at=datetime.now(UTC),
            )
        )


@pytest.mark.asyncio
async def test_folder_name_reservations_include_trashed_and_deleted(db_session):
    from app_core.workspace.domain.folder import (
        Folder,
        FolderExtendedLifecycle,
        FolderName,
    )
    from app_infra.postgres.folder_repository import PostgresFolderRepository

    _, _, project_id = await _workspace_and_project(db_session)
    repository = PostgresFolderRepository(db_session)
    for state in (FolderExtendedLifecycle.TRASHED, FolderExtendedLifecycle.DELETED):
        await repository.save(
            Folder(uuid4(), project_id, None, FolderName(state.value), state)
        )
    reservations = await repository.list_name_reservations(project_id, None)
    assert {item.lifecycle for item in reservations} == {
        FolderExtendedLifecycle.TRASHED,
        FolderExtendedLifecycle.DELETED,
    }


@pytest.mark.asyncio
async def test_move_rejects_self_and_descendant_cycle(db_session):
    from app_core.workspace.domain.folder import Folder, FolderName
    from app_infra.postgres.folder_repository import PostgresFolderRepository

    _, _, project_id = await _workspace_and_project(db_session)
    repository = PostgresFolderRepository(db_session)
    parent = Folder(uuid4(), project_id, None, FolderName("Parent"))
    child = Folder(uuid4(), project_id, parent.folder_id, FolderName("Child"))
    await repository.save(parent)
    await repository.save(child)
    with pytest.raises(ConflictError):
        await repository.move(parent.folder_id, child.folder_id)
    with pytest.raises(ConflictError):
        await repository.move(parent.folder_id, parent.folder_id)


@pytest.mark.asyncio
async def test_trash_restore_folder_changes_only_target_row(db_session):
    from app_core.workspace.domain.folder import (
        Folder,
        FolderExtendedLifecycle,
        FolderName,
    )
    from app_infra.postgres.folder_repository import PostgresFolderRepository

    _, _, project_id = await _workspace_and_project(db_session)
    repository = PostgresFolderRepository(db_session)
    parent = Folder(uuid4(), project_id, None, FolderName("Parent"))
    child = Folder(uuid4(), project_id, parent.folder_id, FolderName("Child"))
    await repository.save(parent)
    await repository.save(child)
    await repository.set_lifecycle(parent.folder_id, FolderExtendedLifecycle.TRASHED)
    assert (
        await repository.find_by_id(parent.folder_id)
    ).lifecycle is FolderExtendedLifecycle.TRASHED
    assert (
        await repository.find_by_id(child.folder_id)
    ).lifecycle is FolderExtendedLifecycle.ACTIVE
    await repository.set_lifecycle(parent.folder_id, FolderExtendedLifecycle.ACTIVE)
    assert (
        await repository.find_by_id(child.folder_id)
    ).lifecycle is FolderExtendedLifecycle.ACTIVE


@pytest.mark.asyncio
async def test_transaction_rollback_removes_project_and_folder_rows(db_session):
    from app_core.workspace.domain.folder import Folder, FolderName
    from app_core.workspace.domain.project import Project, ProjectName
    from app_infra.postgres.folder_repository import PostgresFolderRepository
    from app_infra.postgres.project_repository import PostgresProjectRepository

    workspace_id, creator_id, _ = await _workspace_and_project(db_session)
    project = Project(
        uuid4(), workspace_id, ProjectName("Rollback"), created_by=creator_id
    )
    folder = Folder(uuid4(), project.project_id, None, FolderName("Rollback"))
    await PostgresProjectRepository(db_session).save(project)
    await PostgresFolderRepository(db_session).save(folder)
    await db_session.rollback()
    assert (
        await db_session.scalar(
            text("SELECT count(*) FROM core.projects WHERE project_id=:id"),
            {"id": project.project_id},
        )
        == 0
    )
    assert (
        await db_session.scalar(
            text("SELECT count(*) FROM core.folders WHERE folder_id=:id"),
            {"id": folder.folder_id},
        )
        == 0
    )


@pytest.mark.asyncio
async def test_independent_sessions_prevent_inverse_cycle_moves(db_session):
    from app_core.workspace.domain.folder import Folder, FolderName
    from app_infra.postgres.folder_repository import PostgresFolderRepository

    async with engine.connect() as setup_connection:
        setup_session = AsyncSession(setup_connection)
        _, _, project_id = await _workspace_and_project(setup_session)
        repository = PostgresFolderRepository(setup_session)
        parent = Folder(uuid4(), project_id, None, FolderName("Parent"))
        child = Folder(uuid4(), project_id, parent.folder_id, FolderName("Child"))
        await repository.save(parent)
        await repository.save(child)
        await setup_session.commit()
        await setup_session.close()

    async with (
        engine.connect() as first_connection,
        engine.connect() as second_connection,
    ):
        first, second = AsyncSession(first_connection), AsyncSession(second_connection)
        barrier = asyncio.Barrier(2)

        async def move(session, folder_id, parent_id):
            async with session.begin():
                await barrier.wait()
                return await PostgresFolderRepository(session).move(
                    folder_id, parent_id
                )

        results = await asyncio.wait_for(
            asyncio.gather(
                move(first, parent.folder_id, child.folder_id),
                move(second, child.folder_id, parent.folder_id),
                return_exceptions=True,
            ),
            timeout=10,
        )
        assert any(isinstance(result, ConflictError) for result in results)
        await first.close()
        await second.close()
