"""Arch 15 §13/§14: migration chain release gates.

- expand-first: every upgrade() only ADDS schema (no drop_table/drop_column/
  drop_constraint/drop_index/drop_constraint); contraction lives in downgrade().
- the chain is a single linear head.
- reversibility: downgrade + upgrade round-trips on the guarded isolated DB.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from app_infra.postgres.test_database_guard import require_isolated_database

DATABASE_URL = "postgresql+psycopg://torch@localhost:5432/dom_workspace_lifecycle_test"
MIGRATIONS_DIR = Path("migrations/postgres/versions")

DESTRUCTIVE_UPGRADE = re.compile(
    r"\bop\.(drop_table|drop_column|drop_constraint|drop_index|drop_constraint)"
    r"\s*\("
)


def _config() -> Config:
    config = Config(str(Path("migrations/postgres/alembic.ini")))
    config.set_main_option("sqlalchemy.url", DATABASE_URL)
    return config


def test_upgrade_paths_are_expand_only() -> None:
    violations: list[str] = []
    for path in sorted(MIGRATIONS_DIR.glob("*.py")):
        if path.name == "__init__.py":
            continue
        source = path.read_text()
        upgrade = source.split("def upgrade", 1)
        if len(upgrade) != 2:
            continue
        upgrade_body = upgrade[1].split("def downgrade", 1)[0]
        for match in DESTRUCTIVE_UPGRADE.finditer(upgrade_body):
            violations.append(f"{path.name}: {match.group(0)}")
    assert not violations, "expand-first violation in upgrade(): " + "; ".join(
        violations
    )


def test_single_linear_head() -> None:
    from alembic.script import ScriptDirectory

    script = ScriptDirectory.from_config(_config())
    heads = script.get_heads()
    assert len(heads) == 1, f"expected one head, got {heads}"
    assert heads[0] == "0024"


@pytest.mark.asyncio
async def test_downgrade_then_upgrade_round_trips() -> None:
    database_url = require_isolated_database(os.environ["DATABASE_URL"])
    assert database_url == DATABASE_URL
    config = _config()
    command.downgrade(config, "0009")
    command.upgrade(config, "0014")
    command.downgrade(config, "0009")
    command.upgrade(config, "head")
