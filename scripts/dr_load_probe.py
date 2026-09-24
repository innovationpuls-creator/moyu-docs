"""DR per-workload load probe (arch 15 sign-off): a bounded, synthetic batch
against the ISOLATED database measures rows/sec + bytes/op under write load.
The probe self-cleans its seeded data; the numbers feed the capacity budget
and the per-workload sign-off checklist."""

from __future__ import annotations

import asyncio
import os
import sys
import time
import uuid

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

REQUIRED_DB = "dom_workspace_lifecycle_test"
WORKSPACE_ROWS = 200  # bounded synthetic workload
COMMENT_ROWS = 50
JOURNAL_ROWS = 200


async def main() -> int:
    database_url = os.environ.get("DATABASE_URL", "")
    if REQUIRED_DB not in database_url:
        print("FAIL: probe must run against the isolated database", REQUIRED_DB)
        return 2
    engine = create_async_engine(database_url)
    staged: dict[str, list[str]] = {
        "accounts": [],
        "workspaces": [],
        "projects": [],
        "resources": [],
        "comments": [],
        "journal": [],
    }
    try:
        async with engine.begin() as conn:
            actor = str(uuid.uuid4())
            workspace_id = str(uuid.uuid4())
            project_id = str(uuid.uuid4())
            await conn.execute(
                text(
                    "INSERT INTO auth.accounts "
                    "(account_id,status,primary_email,normalized_email) "
                    "VALUES (:a,'Active',:e,:e)"
                ),
                {"a": actor, "e": f"probe-{actor}@test"},
            )
            await conn.execute(
                text(
                    "INSERT INTO core.workspaces "
                    "(workspace_id,name,status,created_by,created_at,updated_at) "
                    "VALUES (:w,'probe','Active',:a,now(),now())"
                ),
                {"w": workspace_id, "a": actor},
            )
            await conn.execute(
                text(
                    "INSERT INTO core.workspace_members "
                    "(workspace_id,account_id,membership_kind) "
                    "VALUES (:w,:a,'Owner')"
                ),
                {"w": workspace_id, "a": actor},
            )
            await conn.execute(
                text(
                    "INSERT INTO core.projects "
                    "(project_id,workspace_id,name,normalized_name,lifecycle,"
                    "created_by,created_at,updated_at) "
                    "VALUES (:p,:w,'probe','probe','Active',:a,now(),now())"
                ),
                {"p": project_id, "w": workspace_id, "a": actor},
            )
            staged["accounts"].append(actor)
            staged["workspaces"].append(workspace_id)
            staged["projects"].append(project_id)
            started = time.monotonic()
            for _ in range(WORKSPACE_ROWS):
                resource = str(uuid.uuid4())
                await conn.execute(
                    text(
                        "INSERT INTO core.resources "
                        "(resource_id,project_id,resource_type,name,normalized_name,"
                        "lifecycle,schema_version,created_at,updated_at) "
                        "VALUES (:r,:p,'document','w',:n,'Active','1.0.0',"
                        "now(),now())"
                    ),
                    {"r": resource, "p": project_id, "n": str(uuid.uuid4())},
                )
                staged["resources"].append(resource)
                await conn.execute(
                    text(
                        "INSERT INTO collab.resource_update_journal "
                        "(resource_id,journal_seq,ownership_epoch,update_bytes,"
                        "update_hash,accepted_at,durable_at) "
                        "VALUES (:r,1,1,decode('aGVsbG8=','base64'),'h',"
                        "now(),now())"
                    ),
                    {"r": resource},
                )
                staged["journal"].append(resource)
            for _ in range(COMMENT_ROWS):
                await conn.execute(
                    text(
                        "INSERT INTO collab.resource_comments "
                        "(comment_id,thread_id,resource_id,author_account_id,"
                        "anchor,body,deleted,created_at,updated_at) "
                        "VALUES (:c,:t,:r,:a,'{}'::jsonb,:b,false,now(),now())"
                    ),
                    {
                        "c": str(uuid.uuid4()),
                        "t": str(uuid.uuid4()),
                        "r": staged["resources"][0],
                        "a": actor,
                        "b": f"probe {uuid.uuid4()}",
                    },
                )
            elapsed = time.monotonic() - started
            total_rows = WORKSPACE_ROWS + COMMENT_ROWS + JOURNAL_ROWS
            print(
                f"load probe: {total_rows} rows in {elapsed:.2f}s "
                f"-> {total_rows / elapsed:,.0f} rows/s"
            )
            print(
                f"  resources {WORKSPACE_ROWS} + journal {JOURNAL_ROWS} "
                f"+ comments {COMMENT_ROWS}; engine=isolated"
            )
            print("sign-off checklist (record these at per-workload sign-off):")
            print("  - write throughput (rows/s): shown above")
            print("  - bytes/row medians: run scripts/dr_sizing.py")
            print("  - vacuum/Autovacuum behavior: check pg_stat_user_tables")
        # self-clean the probe's seeded data (isolated DB hygiene)
        async with engine.begin() as conn:
            await conn.execute(
                text("DELETE FROM collab.resource_comments WHERE body LIKE 'probe %'")
            )
            for pid in staged["projects"]:
                await conn.execute(
                    text(
                        "DELETE FROM collab.resource_update_journal WHERE "
                        "resource_id IN (SELECT resource_id FROM core.resources "
                        "WHERE project_id=:p)"
                    ),
                    {"p": pid},
                )
                await conn.execute(
                    text("DELETE FROM core.resources WHERE project_id=:p"),
                    {"p": pid},
                )
                await conn.execute(
                    text("DELETE FROM core.projects WHERE project_id=:p"),
                    {"p": pid},
                )
            for wid in staged["workspaces"]:
                await conn.execute(
                    text("DELETE FROM core.workspace_members WHERE workspace_id=:w"),
                    {"w": wid},
                )
                await conn.execute(
                    text("DELETE FROM core.workspaces WHERE workspace_id=:w"),
                    {"w": wid},
                )
            for aid in staged["accounts"]:
                await conn.execute(
                    text("DELETE FROM auth.accounts WHERE account_id=:a"),
                    {"a": aid},
                )
            await conn.execute(
                text(
                    "DELETE FROM collab.resource_update_journal WHERE "
                    "update_hash='h' AND accepted_at > now() - interval "
                    "'10 minutes'"
                )
            )
            await conn.execute(
                text(
                    "DELETE FROM core.resources WHERE name='w' AND "
                    "created_at > now() - interval '10 minutes'"
                )
            )
        print("probe data cleaned.")
        return 0
    finally:
        await engine.dispose()


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
