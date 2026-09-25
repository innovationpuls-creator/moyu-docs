"""Verify the comment-thread migration preserves Resource-scoped identity."""

from __future__ import annotations

import os
from pathlib import Path
from uuid import uuid4

from alembic import command
from alembic.config import Config
from app_infra.postgres.test_database_guard import require_isolated_database
from sqlalchemy import create_engine, inspect, text


def _alembic_config(database_url: str) -> Config:
    config = Config(str(Path("migrations/postgres/alembic.ini")))
    config.set_main_option("sqlalchemy.url", database_url)
    return config


def test_comment_thread_migration_keeps_same_id_per_resource_separate() -> None:
    database_url = require_isolated_database(os.environ["DATABASE_URL"])
    config = _alembic_config(database_url)
    command.downgrade(config, "base")
    command.upgrade(config, "0018")

    account_a, account_b = uuid4(), uuid4()
    workspace_id, project_id = uuid4(), uuid4()
    resource_a, resource_b = uuid4(), uuid4()
    shared_thread_id = uuid4()
    engine = create_engine(database_url)
    try:
        with engine.begin() as connection:
            for account_id in (account_a, account_b):
                connection.execute(
                    text(
                        "INSERT INTO auth.accounts "
                        "(account_id,status,primary_email,normalized_email) "
                        "VALUES (:account_id,'Active',:email,:email)"
                    ),
                    {
                        "account_id": account_id,
                        "email": f"migration-{account_id}@test",
                    },
                )
            connection.execute(
                text(
                    "INSERT INTO core.workspaces "
                    "(workspace_id,name,status,created_by) "
                    "VALUES (:id,'Migration','Active',:creator)"
                ),
                {"id": workspace_id, "creator": account_a},
            )
            connection.execute(
                text(
                    "INSERT INTO core.workspace_members "
                    "(workspace_id,account_id,membership_kind) "
                    "VALUES (:workspace,:account,'Owner')"
                ),
                {"workspace": workspace_id, "account": account_a},
            )
            connection.execute(
                text(
                    "INSERT INTO core.projects "
                    "(project_id,workspace_id,name,normalized_name,created_by) "
                    "VALUES (:id,:workspace,'Migration','migration',:creator)"
                ),
                {
                    "id": project_id,
                    "workspace": workspace_id,
                    "creator": account_a,
                },
            )
            for resource_id, name in ((resource_a, "A"), (resource_b, "B")):
                connection.execute(
                    text(
                        "INSERT INTO core.resources "
                        "(resource_id,project_id,resource_type,name,normalized_name,"
                        "created_by) VALUES (:id,:project,'document',:name,:normalized,"
                        ":creator)"
                    ),
                    {
                        "id": resource_id,
                        "project": project_id,
                        "name": name,
                        "normalized": name.lower(),
                        "creator": account_a,
                    },
                )
            for resource_id, account_id in (
                (resource_a, account_a),
                (resource_b, account_b),
            ):
                connection.execute(
                    text(
                        "INSERT INTO collab.resource_comments "
                        "(comment_id,thread_id,resource_id,author_account_id,"
                        "anchor,body) VALUES (:comment,:thread,:resource,:author,"
                        "'{}'::jsonb,'legacy')"
                    ),
                    {
                        "comment": uuid4(),
                        "thread": shared_thread_id,
                        "resource": resource_id,
                        "author": account_id,
                    },
                )

        command.upgrade(config, "head")
        with engine.connect() as connection:
            rows = (
                connection.execute(
                    text(
                        "SELECT resource_id,thread_id,created_by "
                        "FROM collab.comment_threads WHERE thread_id=:thread "
                        "ORDER BY resource_id"
                    ),
                    {"thread": shared_thread_id},
                )
                .mappings()
                .all()
            )
            assert {(row["resource_id"], row["created_by"]) for row in rows} == {
                (resource_a, account_a),
                (resource_b, account_b),
            }

        inspector = inspect(engine)
        primary_key = inspector.get_pk_constraint("comment_threads", schema="collab")
        assert primary_key["constrained_columns"] == ["resource_id", "thread_id"]
        thread_foreign_key = next(
            foreign_key
            for foreign_key in inspector.get_foreign_keys(
                "resource_comments", schema="collab"
            )
            if foreign_key["name"] == "fk_comments_thread"
        )
        assert thread_foreign_key["constrained_columns"] == [
            "resource_id",
            "thread_id",
        ]
        assert thread_foreign_key["referred_columns"] == [
            "resource_id",
            "thread_id",
        ]
    finally:
        engine.dispose()
        command.upgrade(config, "head")
