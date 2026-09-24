from __future__ import annotations

from datetime import UTC, datetime

from app_core.workspace.application.purge.enqueuer import (
    PURGE_TASK_TYPE,
    purge_task_id,
)
from app_core.workspace.ports.purge import WorkspacePurgeRepository
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


class PostgresWorkspacePurgeEnqueuer:
    def __init__(
        self, session: AsyncSession, candidates: WorkspacePurgeRepository
    ) -> None:
        self._session = session
        self._candidates = candidates

    async def enqueue(self, now: datetime, limit: int) -> int:
        candidates = await self._candidates.candidates_before(now, limit)
        enqueued = 0
        for candidate in candidates:
            task_id = purge_task_id(candidate.workspace_id)
            result = await self._session.execute(
                text(
                    "INSERT INTO work.tasks "
                    "(task_id,task_type,state,priority,input_ref,created_at,queued_at,"
                    "schema_version) VALUES "
                    "(:task_id,:task_type,'Queued','Maintenance',"
                    ":input_ref,:now,:now,'1.0.0') ON CONFLICT (task_id) DO NOTHING"
                ),
                {
                    "task_id": task_id,
                    "task_type": PURGE_TASK_TYPE,
                    "input_ref": str(candidate.workspace_id),
                    "now": now.astimezone(UTC),
                },
            )
            enqueued += result.rowcount  # type: ignore[attr-defined]
        return enqueued
