from __future__ import annotations

import io
from pathlib import Path

from alembic import command
from alembic.config import Config


def test_permission_collaboration_migration_emits_schema_and_owner_guards() -> None:
    config = Config(str(Path("migrations/postgres/alembic.ini")))
    config.set_main_option("sqlalchemy.url", "postgresql+psycopg://offline")
    output = io.StringIO()
    config.output_buffer = output

    command.upgrade(config, "0021", sql=True)

    sql = output.getvalue()
    assert "CREATE TABLE core.project_members" in sql
    assert "CREATE TABLE core.resource_permissions" in sql
    assert "CREATE TABLE core.invitations" in sql
    assert "token_hash" in sql
    assert "trg_project_owner_membership_invariant" in sql
    assert "trg_projects_seed_initial_owner" in sql
