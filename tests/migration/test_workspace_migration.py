import io
import os
from pathlib import Path
from urllib.parse import urlparse

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect


@pytest.fixture
def database_url() -> str:
    value = os.environ.get("DATABASE_URL")
    if value is None:
        pytest.fail(
            "DATABASE_URL must explicitly target the isolated migration test DB"
        )
    parsed = urlparse(value)
    if parsed.path.lstrip("/") != "dom_workspace_lifecycle_test":
        pytest.fail("DATABASE_URL must target dom_workspace_lifecycle_test")
    return value


def _alembic_config(database_url: str) -> Config:
    config = Config(str(Path("migrations/postgres/alembic.ini")))
    config.set_main_option("sqlalchemy.url", database_url)
    return config


def test_workspace_migration_emits_lifecycle_tables() -> None:
    config = _alembic_config("postgresql+psycopg://offline")
    output = io.StringIO()
    config.output_buffer = output

    command.upgrade(config, "0002", sql=True)

    sql = output.getvalue()
    assert "CREATE SCHEMA IF NOT EXISTS core" in sql
    for table in ("workspaces", "projects", "folders"):
        assert f"CREATE TABLE core.{table}" in sql
    assert "CREATE TABLE core.workspace_members" not in sql
    assert "CREATE TABLE core.project_members" not in sql
    assert "CREATE TABLE core.resource_permissions" not in sql


def test_workspace_migration_creates_lifecycle_schema(database_url: str) -> None:
    config = _alembic_config(database_url)
    command.downgrade(config, "base")
    command.upgrade(config, "0001")
    command.upgrade(config, "0002")

    engine = create_engine(database_url)
    try:
        inspector = inspect(engine)
        expected_tables = {"workspaces", "projects", "folders"}
        assert expected_tables <= set(inspector.get_table_names(schema="core"))
        assert not {
            "workspace_members",
            "project_members",
            "resource_permissions",
        } & set(inspector.get_table_names(schema="core"))

        workspace_columns = {
            column["name"]: column
            for column in inspector.get_columns("workspaces", schema="core")
        }
        assert workspace_columns["created_by"]["nullable"] is False
        workspace_foreign_keys = inspector.get_foreign_keys("workspaces", schema="core")
        assert any(
            foreign_key["constrained_columns"] == ["created_by"]
            and foreign_key["referred_schema"] == "auth"
            and foreign_key["referred_table"] == "accounts"
            and foreign_key["referred_columns"] == ["account_id"]
            for foreign_key in workspace_foreign_keys
        )

        project_columns = {
            column["name"]: column
            for column in inspector.get_columns("projects", schema="core")
        }
        assert project_columns["created_by"]["nullable"] is False
        project_foreign_keys = inspector.get_foreign_keys("projects", schema="core")
        assert any(
            foreign_key["constrained_columns"] == ["created_by"]
            and foreign_key["referred_schema"] == "auth"
            and foreign_key["referred_table"] == "accounts"
            and foreign_key["referred_columns"] == ["account_id"]
            for foreign_key in project_foreign_keys
        )
        assert {
            "project_id",
            "workspace_id",
            "name",
            "normalized_name",
            "lifecycle",
            "archived_at",
            "trashed_at",
        } <= set(project_columns)

        folder_foreign_keys = inspector.get_foreign_keys("folders", schema="core")
        assert any(
            foreign_key["constrained_columns"] == ["project_id"]
            and foreign_key["referred_table"] == "projects"
            and foreign_key["referred_columns"] == ["project_id"]
            for foreign_key in folder_foreign_keys
        )
        assert any(
            foreign_key["constrained_columns"] == ["parent_folder_id", "project_id"]
            and foreign_key["referred_table"] == "folders"
            and foreign_key["referred_columns"] == ["folder_id", "project_id"]
            for foreign_key in folder_foreign_keys
        )
        folder_indexes = inspector.get_indexes("folders", schema="core")
        assert {index["name"] for index in folder_indexes} >= {
            "uq_folders_project_root_name",
            "uq_folders_parent_name",
            "ix_folders_project_id",
            "ix_folders_parent_folder_id",
        }
    finally:
        engine.dispose()

    command.downgrade(config, "0001")
    engine = create_engine(database_url)
    try:
        assert inspect(engine).get_table_names(schema="core") == []
    finally:
        engine.dispose()

    command.upgrade(config, "head")
