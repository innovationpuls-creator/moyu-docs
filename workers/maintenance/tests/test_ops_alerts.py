"""Guarded proof: the sweep evaluates alert rules and persists breaches into
the audit trail (arch 14)."""

from __future__ import annotations

import json

import pytest
from app_infra.postgres.engine import engine
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


@pytest.mark.asyncio
async def test_alert_breach_lands_in_audit_trail(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPS_ALERT_DB_CONNECTIONS", "0")
    connection = await engine.connect()
    session = AsyncSession(connection)
    transaction = None
    try:
        existing_ids = set(
            (
                await session.execute(
                    text(
                        "SELECT entry_id FROM core.audit_entries WHERE action="
                        "'system.alert' AND detail->>'rule'='db.connections' "
                        "AND detail->>'threshold'='0'"
                    )
                )
            )
            .scalars()
            .all()
        )
        await session.rollback()
        from app_infra.postgres.ops_alerts import PostgresOpsAlerts

        transaction = await session.begin()
        # threshold 0 -> any live connection breaches deterministically
        breached = await PostgresOpsAlerts(session).evaluate()
        assert "db.connections" in breached
        new_entries = (
            (
                await session.execute(
                    text(
                        "SELECT entry_id,detail FROM core.audit_entries "
                        "WHERE action='system.alert' AND "
                        "detail->>'rule'='db.connections' AND "
                        "detail->>'threshold'='0'"
                    )
                )
            )
            .mappings()
            .all()
        )
        created_entries = [
            row for row in new_entries if row["entry_id"] not in existing_ids
        ]
        assert created_entries
        details = [
            row["detail"]
            if isinstance(row["detail"], dict)
            else json.loads(row["detail"])
            for row in created_entries
        ]
        assert any(detail.get("rule") == "db.connections" for detail in details)
        assert any(detail.get("threshold") == 0 for detail in details)
    finally:
        if transaction is not None:
            await transaction.rollback()
        await session.close()
        await connection.close()
