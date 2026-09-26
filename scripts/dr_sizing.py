"""DR production sizing budget (arch 15): per-table bytes/row sampled from the
isolated DB (guarded), projected to 10k/100k/1M-resource growth scenarios.

Boundary: SAMPLED estimates (first 500 rows per table), not a load test; the
numbers feed the capacity budget in docs/runbooks/disaster-recovery.md.
"""

from __future__ import annotations

import asyncio
import os
import sys

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, create_async_engine

REQUIRED_DB = "dom_workspace_lifecycle_test"
SCENARIOS = ("10k", "100k", "1m")
# tables whose row count scales with the resource population
SCALING_TABLES = (
    "core.resources",
    "core.folders",
    "collab.notifications",
    "collab.resource_update_journal",
    "collab.resource_checkpoints",
    "collab.resource_comments",
    "collab.resource_search_index",
    "collab.resource_named_versions",
    "work.tasks",
)


async def _row_estimate(conn: AsyncConnection, schema: str, table: str) -> int:
    row = (
        await conn.execute(
            text(
                "SELECT c.reltuples::bigint FROM pg_class c "
                "JOIN pg_namespace n ON n.oid=c.relnamespace "
                "WHERE n.nspname=:s AND c.relname=:t"
            ),
            {"s": schema, "t": table},
        )
    ).scalar()
    reltuples = int(row or 0)
    if reltuples < 0:
        counted = (
            await conn.execute(text(f"SELECT COUNT(*)::bigint FROM {schema}.{table}"))
        ).scalar()
        reltuples = int(counted or 0)
    return reltuples


async def _sample_rows(
    conn: AsyncConnection,
) -> tuple[dict[str, int], dict[str, float]]:
    print(f"{'table':<34}{'rows':>12}{'B/row':>9}{'est MB':>10}")
    totals: dict[str, int] = {}
    for qualified in SCALING_TABLES:
        schema, table = qualified.split(".", 1)
        reltuples = await _row_estimate(conn, schema, table)
        avg = (
            await conn.execute(
                text(
                    f"SELECT COALESCE(AVG(pg_column_size(t.*)),0)::int "
                    f"FROM (SELECT * FROM {schema}.{table} LIMIT 500) t"
                )
            )
        ).scalar()
        bytes_per_row = int(avg or 0)
        est_mb = reltuples * bytes_per_row / (1024 * 1024)
        print(f"{schema}.{table:<28}{reltuples:>12}{bytes_per_row:>9}{est_mb:>10.1f}")
        totals[schema + "." + table] = bytes_per_row
    factors = await _measured_factors(conn)
    print()
    print("measured per-resource factors (bytes, from live rows):")
    for name, value in factors.items():
        print(f"  {name}: {value}")
    print()
    return totals, factors


async def _measured_factors(conn: AsyncConnection) -> dict[str, float]:
    journal = (
        await conn.execute(
            text(
                "SELECT COALESCE(AVG(length(update_bytes)),0)::float FROM "
                "(SELECT update_bytes FROM collab.resource_update_journal "
                "LIMIT 500) t"
            )
        )
    ).scalar()
    comment = (
        await conn.execute(
            text(
                "SELECT COALESCE(AVG(length(body)),0)::float FROM "
                "(SELECT body FROM collab.resource_comments LIMIT 500) t"
            )
        )
    ).scalar()
    checkpoint = (
        await conn.execute(
            text(
                "SELECT COALESCE(AVG(length(snapshot::text)),0)::float FROM "
                "(SELECT snapshot FROM collab.resource_checkpoints LIMIT 500) t"
            )
        )
    ).scalar()
    return {
        "journal.op_bytes": float(journal or 0),
        "comment.bytes": float(comment or 0),
        "checkpoint.bytes": float(checkpoint or 0),
    }


def _factor_for(factors: dict[str, float], table: str) -> float:
    if table in ("resources", "folders", "notifications"):
        return 1.0
    if table == "resource_update_journal":
        return factors["journal.op_bytes"] or 50.0
    if table == "resource_comments":
        return factors["comment.bytes"] or 50.0
    if table == "resource_checkpoints":
        return factors["checkpoint.bytes"] or 5.0
    if table == "resource_search_index":
        return 5.0
    if table == "resource_named_versions":
        return 3.0
    if table == "tasks":
        return 8.0
    return 1.0


async def _project(totals: dict[str, int], factors: dict[str, float]) -> None:
    for label in SCENARIOS:
        count = int(label[:-1]) * (1000 if label[-1] == "k" else 1_000_000)
        total = 0.0
        for key, bpr in totals.items():
            total += count * _factor_for(factors, key.partition(".")[2]) * bpr
        mb = total / (1024 * 1024)
        print(f"  {label} resources: ~{mb:,.0f} MB")


async def main() -> int:
    database_url = os.environ.get("DATABASE_URL", "")
    if REQUIRED_DB not in database_url:
        print("FAIL: sizing must run against the isolated database", REQUIRED_DB)
        return 2
    engine = create_async_engine(database_url)
    try:
        async with engine.connect() as conn:
            totals, factors = await _sample_rows(conn)
            print("projected storage per scenario (top scaling tables):")
            await _project(totals, factors)
            return 0
    finally:
        await engine.dispose()


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
