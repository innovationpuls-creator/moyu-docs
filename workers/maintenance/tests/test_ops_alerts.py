"""Guarded proof: the sweep evaluates alert rules and persists breaches into
the audit trail (arch 14)."""

from __future__ import annotations

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
    try:
        async with session.begin():
            await session.execute(
                text("DELETE FROM core.audit_entries WHERE action='system.alert'")
            )
        from app_infra.postgres.ops_alerts import PostgresOpsAlerts

        async with session.begin():
            # threshold 0 -> any live connection breaches deterministically
            breached = await PostgresOpsAlerts(session).evaluate()
        assert "db.connections" in breached
        entries = (
            (
                await session.execute(
                    text(
                        "SELECT detail FROM core.audit_entries "
                        "WHERE action='system.alert'"
                    )
                )
            )
            .scalars()
            .all()
        )
        assert len(entries) == 1
        detail = (
            entries[0]
            if isinstance(entries[0], dict)
            else __import__("json").loads(entries[0])
        )
        assert detail["rule"] == "db.connections"
        assert detail["threshold"] == 0  # the env-overridden rule
    finally:
        await session.close()
        await connection.close()
