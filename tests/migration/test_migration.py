import io
import os
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect


@pytest.fixture
def postgres_dsn() -> str:
    return os.getenv(
        "DATABASE_URL",
        "postgresql+psycopg://postgres:postgres@localhost:5432/dom_dev",
    )


def _alembic_config(postgres_dsn: str) -> Config:
    config = Config(str(Path("migrations/postgres/alembic.ini")))
    config.set_main_option("sqlalchemy.url", postgres_dsn)
    return config


def test_offline_migration_emits_required_schemas_and_tables() -> None:
    config = Config(str(Path("migrations/postgres/alembic.ini")))
    config.set_main_option("sqlalchemy.url", "postgresql+psycopg://offline")
    output = io.StringIO()
    config.output_buffer = output
    command.upgrade(config, "head", sql=True)
    sql = output.getvalue()
    for schema in ("auth", "audit", "integration"):
        assert f"CREATE SCHEMA IF NOT EXISTS {schema}" in sql
    for table in (
        "accounts",
        "identities",
        "password_credentials",
        "sessions",
        "one_time_tokens",
        "account_deletion_requests",
    ):
        assert f"CREATE TABLE auth.{table}" in sql
    assert "CREATE TABLE audit.entries" in sql
    assert "CREATE TABLE integration.outbox_events" in sql
    assert "ix_outbox_events_unpublished" in sql


def test_alembic_upgrade_and_downgrade(postgres_dsn: str) -> None:
    config = _alembic_config(postgres_dsn)
    command.downgrade(config, "base")
    command.upgrade(config, "head")

    engine = create_engine(postgres_dsn)
    try:
        inspector = inspect(engine)
        expected_tables = {
            "auth": {
                "accounts",
                "identities",
                "password_credentials",
                "sessions",
                "one_time_tokens",
                "account_deletion_requests",
            },
            "audit": {"entries"},
            "integration": {"outbox_events"},
        }
        for schema, tables in expected_tables.items():
            assert tables <= set(inspector.get_table_names(schema=schema))

        assert {
            "audit_id",
            "occurred_at",
            "actor_type",
            "actor_id",
            "action",
            "workspace_id",
            "project_id",
            "resource_id",
            "target_ref",
            "request_id",
            "trace_id",
            "metadata",
        } <= {
            column["name"]
            for column in inspector.get_columns("entries", schema="audit")
        }
        outbox_columns = {
            column["name"]: column
            for column in inspector.get_columns("outbox_events", schema="integration")
        }
        assert {
            "outbox_id",
            "event_id",
            "event_type",
            "schema_version",
            "aggregate_type",
            "aggregate_id",
            "payload",
            "trace_id",
            "created_at",
            "published_at",
            "publish_attempts",
        } <= set(outbox_columns)
        assert outbox_columns["event_id"]["nullable"] is False
        assert outbox_columns["payload"]["nullable"] is False
        assert outbox_columns["publish_attempts"]["default"] == "0"

        token_columns = {
            column["name"]: column
            for column in inspector.get_columns("one_time_tokens", schema="auth")
        }
        assert token_columns["account_id"]["nullable"] is True

        identity_uniques = inspector.get_unique_constraints("identities", schema="auth")
        assert any(
            constraint["column_names"] == ["provider", "provider_subject"]
            for constraint in identity_uniques
        )
        outbox_uniques = inspector.get_unique_constraints(
            "outbox_events", schema="integration"
        )
        assert any(
            constraint["column_names"] == ["event_id"] for constraint in outbox_uniques
        )

        assert {
            tuple(foreign_key["constrained_columns"])
            for foreign_key in inspector.get_foreign_keys("identities", schema="auth")
        } == {("account_id",)}
        assert {
            tuple(foreign_key["constrained_columns"])
            for foreign_key in inspector.get_foreign_keys("sessions", schema="auth")
        } == {("account_id",)}
        assert {
            tuple(foreign_key["constrained_columns"])
            for foreign_key in inspector.get_foreign_keys(
                "one_time_tokens", schema="auth"
            )
        } == {("account_id",)}

        account_indexes = inspector.get_indexes("accounts", schema="auth")
        assert any(
            index["name"] == "ix_accounts_normalized_email" and index["unique"]
            for index in account_indexes
        )
        session_indexes = inspector.get_indexes("sessions", schema="auth")
        assert {index["name"] for index in session_indexes} >= {
            "ix_sessions_account_status",
            "ix_sessions_account_created",
        }
    finally:
        engine.dispose()

    command.downgrade(config, "base")
    engine = create_engine(postgres_dsn)
    try:
        inspector = inspect(engine)
        for schema in ("auth", "audit", "integration"):
            assert inspector.get_table_names(schema=schema) == []
    finally:
        engine.dispose()

    command.upgrade(config, "head")
