"""Alert-rule evaluation (arch 14): the maintenance sweep checks threshold
rules over lightweight DB gauges and records breaches into the audit trail
(action 'system.alert'); thresholds come from env (OPS_ALERT_*), defaults are
deliberately high so the dev harness stays quiet."""

from __future__ import annotations

import json
import os
from uuid import uuid4

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

DEFAULT_ALERTS = {
    "sessions.active": 100000,
    "resources.active": 1000000,
    "db.connections": 100,
}


class PostgresOpsAlerts:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    def _thresholds(self) -> dict[str, int]:
        out: dict[str, int] = {}
        for name, default in DEFAULT_ALERTS.items():
            env = os.environ.get(f"OPS_ALERT_{name.replace('.', '_').upper()}")
            out[name] = int(env) if env else default
        return out

    async def evaluate(self) -> list[str]:
        """Return the breached rule names (and persist each breach once)."""
        rows = (
            (
                await self._session.execute(
                    text(
                        "SELECT (SELECT COUNT(*) FROM auth.sessions "
                        "WHERE expires_at > now()) AS sessions_active, "
                        "(SELECT COUNT(*) FROM core.resources "
                        "WHERE lifecycle='Active') AS resources_active, "
                        "(SELECT COUNT(*) FROM pg_stat_activity) "
                        "AS db_connections"
                    )
                )
            )
            .mappings()
            .first()
        )
        if rows is None:
            return []
        column = {
            "sessions.active": "sessions_active",
            "resources.active": "resources_active",
            "db.connections": "db_connections",
        }
        breached: list[str] = []
        for name, threshold in self._thresholds().items():
            value = int(rows[column[name]])
            if value > threshold:
                breached.append(name)
                await self._session.execute(
                    text(
                        "INSERT INTO core.audit_entries "
                        "(entry_id,actor_account_id,action,target_type,"
                        "target_id,detail) "
                        "VALUES (:eid,NULL,'system.alert','ops',NULL,:detail)"
                    ),
                    {
                        "eid": uuid4(),
                        "detail": json.dumps(
                            {"rule": name, "value": value, "threshold": threshold}
                        ),
                    },
                )
        return breached
