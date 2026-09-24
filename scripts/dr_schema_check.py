"""DR readiness baseline (arch 15): the isolated schema matches the frozen
table inventory and the migration head; runnable on dom_workspace_lifecycle_test.

Boundary: this verifies the SCHEMA contract for backup/restore feasibility
(reproducibility surface), not the data itself; a pg_dump drill is documented
in docs/runbooks/disaster-recovery.md.
"""

from __future__ import annotations

import asyncio
import os
import sys

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

REQUIRED_DB = "dom_workspace_lifecycle_test"
EXPECTED_HEAD = "0017"

# (schema, table) pairs frozen by the migration chain + domain owners
SCHEMA_INVENTORY: tuple[tuple[str, str], ...] = (
    ("auth", "accounts"),
    ("auth", "sessions"),
    ("core", "workspaces"),
    ("core", "workspace_members"),
    ("core", "projects"),
    ("core", "folders"),
    ("core", "resources"),
    ("core", "notifications"),
    ("core", "search_history"),
    ("core", "webhook_subscriptions"),
    ("core", "audit_entries"),
    ("core", "integration_keys"),
    ("collab", "resource_update_journal"),
    ("collab", "resource_checkpoints"),
    ("collab", "resource_comments"),
    ("collab", "resource_assets"),
    ("collab", "resource_search_index"),
    ("collab", "resource_named_versions"),
    ("collab", "resource_ownership"),
    ("collab", "ai_changesets"),
    ("work", "tasks"),
    ("work", "task_attempts"),
    ("work", "task_effects"),
)


async def main() -> int:
    database_url = os.environ.get("DATABASE_URL", "")
    if REQUIRED_DB not in database_url:
        print("FAIL: DR check must run against the isolated database", REQUIRED_DB)
        return 2
    engine = create_async_engine(database_url)
    problems: list[str] = []
    try:
        async with engine.connect() as conn:
            head = (
                await conn.execute(text("SELECT version_num FROM alembic_version"))
            ).scalar()
            if head != EXPECTED_HEAD:
                problems.append(f"head={head!r} expected {EXPECTED_HEAD!r}")
            for schema, table in SCHEMA_INVENTORY:
                exists = (
                    await conn.execute(
                        text(
                            "SELECT 1 FROM information_schema.tables "
                            "WHERE table_schema=:s AND table_name=:t"
                        ),
                        {"s": schema, "t": table},
                    )
                ).scalar()
                if exists != 1:
                    problems.append(f"missing {schema}.{table}")
    finally:
        await engine.dispose()
    if problems:
        print("FAIL: " + "; ".join(problems))
        return 1
    print(
        f"PASS: isolated schema matches inventory ({len(SCHEMA_INVENTORY)} "
        f"tables), head={EXPECTED_HEAD}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
