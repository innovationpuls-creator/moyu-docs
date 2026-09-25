from __future__ import annotations

import os
from pathlib import Path
from uuid import uuid4

import pytest
import pytest_asyncio
from alembic import command
from alembic.config import Config
from app_infra.postgres.engine import engine
from app_infra.postgres.resource.resource_repository import PostgresResourceRepository
from app_infra.postgres.resource_ownership_repository import (
    PostgresResourceOwnershipRepository,
)
from app_infra.postgres.test_database_guard import require_isolated_database
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

DATABASE_URL = "postgresql+psycopg://torch@localhost:5432/dom_workspace_lifecycle_test"


@pytest_asyncio.fixture(scope="module", autouse=True)
async def migrated_database() -> None:
    database_url = require_isolated_database(os.environ["DATABASE_URL"])
    assert database_url == DATABASE_URL
    config = Config(str(Path("migrations/postgres/alembic.ini")))
    config.set_main_option("sqlalchemy.url", database_url)
    command.upgrade(config, "head")


async def _seed_project(session: AsyncSession) -> tuple[str, str]:
    account_id = uuid4()
    workspace_id = uuid4()
    project_id = uuid4()
    await session.execute(
        text(
            "INSERT INTO auth.accounts "
            "(account_id,status,primary_email,normalized_email) "
            "VALUES (:a,'Active',:e,:e)"
        ),
        {"a": account_id, "e": f"own-{account_id}@test"},
    )
    await session.execute(
        text(
            "INSERT INTO core.workspaces "
            "(workspace_id,name,status,created_by,created_at,updated_at) "
            "VALUES (:w,'W','Active',:a,now(),now())"
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
    return str(project_id), str(account_id)


@pytest.mark.asyncio
async def test_ownership_grant_transfer_and_authorize() -> None:
    connection = await engine.connect()
    session = AsyncSession(connection)
    try:
        async with session.begin():
            project_id, owner_id = await _seed_project(session)
            resource = await PostgresResourceRepository(session).create(
                project_id=project_id,
                resource_type="document",
                name="Doc",
                normalized_name="doc",
            )
        other = uuid4()
        async with session.begin():
            await session.execute(
                text(
                    "INSERT INTO auth.accounts "
                    "(account_id,status,primary_email,normalized_email) "
                    "VALUES (:a,'Active',:e,:e)"
                ),
                {"a": other, "e": f"own-{other}@test"},
            )
        ownership = PostgresResourceOwnershipRepository(session)
        async with session.begin():
            first = await ownership.grant(resource.resource_id, owner_id)
            second = await ownership.grant(resource.resource_id, other)
        assert first.epoch == 1
        assert second.epoch == 2  # transfer bumps epoch (arch 29 §45)
        async with session.begin():
            assert not await ownership.authorize(
                other, resource.resource_id, "resource.update"
            )
            await session.execute(
                text(
                    "INSERT INTO core.project_members "
                    "(project_id,account_id,role,membership_kind,created_at,"
                    "updated_at) "
                    "VALUES (:project_id,:account_id,'Edit','Member',now(),now())"
                ),
                {"project_id": project_id, "account_id": other},
            )
            assert await ownership.authorize(
                other, resource.resource_id, "resource.update"
            )
            assert await ownership.authorize(
                owner_id, resource.resource_id, "resource.update"
            )
    finally:
        await session.close()
        await connection.close()


@pytest.mark.asyncio
async def test_authorization_respects_project_and_resource_lifecycle() -> None:
    connection = await engine.connect()
    session = AsyncSession(connection)
    try:
        async with session.begin():
            project_id, owner_id = await _seed_project(session)
            resource = await PostgresResourceRepository(session).create(
                project_id=project_id,
                resource_type="document",
                name="Lifecycle document",
                normalized_name="lifecycle-document",
            )
        ownership = PostgresResourceOwnershipRepository(session)
        async with session.begin():
            assert await ownership.authorize(
                owner_id, resource.resource_id, "resource.update"
            )
            await session.execute(
                text(
                    "UPDATE core.projects SET lifecycle='Archived' WHERE project_id=:id"
                ),
                {"id": project_id},
            )
            assert await ownership.authorize(
                owner_id, resource.resource_id, "resource.read"
            )
            assert not await ownership.authorize(
                owner_id, resource.resource_id, "resource.update"
            )
            await session.execute(
                text(
                    "UPDATE core.resources SET lifecycle='Trashed' "
                    "WHERE resource_id=:id"
                ),
                {"id": resource.resource_id},
            )
            assert not await ownership.authorize(
                owner_id, resource.resource_id, "resource.read"
            )
            assert not await ownership.authorize(
                owner_id, resource.resource_id, "resource.update"
            )
    finally:
        await session.close()
        await connection.close()
