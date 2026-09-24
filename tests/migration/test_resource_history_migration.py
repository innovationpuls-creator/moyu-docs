"""Guarded migration round-trip for 0005..head (isolated DB only)."""

from __future__ import annotations

import os
from pathlib import Path
from urllib.parse import urlparse

from alembic import command
from alembic.config import Config

DATABASE_URL = "postgresql+psycopg://torch@localhost:5432/dom_workspace_lifecycle_test"


def test_resource_history_migration_round_trip() -> None:
    value = os.environ.get("DATABASE_URL")
    assert value is not None, "DATABASE_URL must target the isolated migration DB"
    assert urlparse(value).path.lstrip("/") == "dom_workspace_lifecycle_test"
    config = Config(str(Path("migrations/postgres/alembic.ini")))
    config.set_main_option("sqlalchemy.url", value)
    command.downgrade(config, "0004")
    command.upgrade(config, "head")
    assert True
