"""Webhook dead-letter retention (arch 10 §DLQ): Failed webhook.deliver rows
older than the retention window are purged by the maintenance sweep; Queued /
Running / Retrying rows are NEVER touched (expanding out of the DL state is
the only way a task leaves the dead-letter surface)."""

from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

DEFAULT_RETENTION_DAYS = 14


class PostgresWebhookRetention:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def run(self, *, older_than_days: int = DEFAULT_RETENTION_DAYS) -> int:
        result = await self._session.execute(
            text(
                "DELETE FROM work.tasks WHERE task_type='webhook.deliver' "
                "AND state='Failed' AND "
                "created_at < now() - (CAST(:days AS interval))"
            ),
            {"days": f"{older_than_days} days"},
        )
        return int(getattr(result, "rowcount", 0) or 0)
