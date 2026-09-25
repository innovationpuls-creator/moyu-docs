"""Guarded integration: comments over the real chain (migration 0009)."""

from __future__ import annotations

import os
from pathlib import Path
from uuid import uuid4

import pytest
import pytest_asyncio
from alembic import command
from alembic.config import Config
from app_core.comments.application import AddComment, ListComments
from app_core.comments.domain import CommentPermissionDeniedError
from app_infra.postgres.comments_repository import PostgresCommentsRepository
from app_infra.postgres.engine import engine
from app_infra.postgres.resource.resource_repository import (
    PostgresResourceRepository,
)
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


@pytest.mark.asyncio
async def test_comment_chain_and_permission() -> None:
    connection = await engine.connect()
    session = AsyncSession(connection)
    try:
        account_id = uuid4()
        workspace_id = uuid4()
        project_id = uuid4()
        outsider = uuid4()
        async with session.begin():
            await session.execute(
                text(
                    "INSERT INTO auth.accounts "
                    "(account_id,status,primary_email,normalized_email) "
                    "VALUES (:a,'Active',:e,:e)"
                ),
                {"a": account_id, "e": f"cm-{account_id}@test"},
            )
            await session.execute(
                text(
                    "INSERT INTO auth.accounts "
                    "(account_id,status,primary_email,normalized_email) "
                    "VALUES (:a,'Active',:e,:e)"
                ),
                {"a": outsider, "e": f"cm-{outsider}@test"},
            )
            await session.execute(
                text(
                    "INSERT INTO core.workspaces "
                    "(workspace_id,name,status,created_by,created_at,updated_at) "
                    "VALUES (:w,'C','Active',:a,now(),now())"
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
                name="Doc",
                normalized_name="doc",
            )
            await PostgresResourceOwnershipRepository(session).grant(
                resource.resource_id, account_id
            )
        comments = PostgresCommentsRepository(session)
        ownership = PostgresResourceOwnershipRepository(session)
        add = AddComment(comments, ownership)
        async with session.begin():
            root = await add.execute(
                account_id, resource.resource_id, body="整体缺异常流程"
            )
        assert root.body == "整体缺异常流程"
        assert root.anchor == {"type": "ResourceAnchor"}
        async with session.begin():
            reply = await add.execute(
                account_id,
                resource.resource_id,
                body="补充一下",
                thread_id=root.thread_id,
            )
        assert reply.thread_id == root.thread_id
        async with session.begin():
            listed = await ListComments(comments, ownership).execute(
                account_id, resource.resource_id
            )
        assert [c.comment_id for c in listed] == [root.comment_id, reply.comment_id]
        async with session.begin():
            with pytest.raises(CommentPermissionDeniedError):
                await add.execute(outsider, resource.resource_id, body="no")
    finally:
        await session.close()
        await connection.close()
