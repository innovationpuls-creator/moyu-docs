from __future__ import annotations

from typing import Any
from uuid import UUID, uuid5

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

_NAMESPACE = UUID("8d8e31d2-9b2f-4c77-9e0a-6c47f2a9eb21")


def _purge_task_id(resource_id: UUID) -> UUID:
    return uuid5(_NAMESPACE, f"resource.purge:{resource_id}")


class PostgresResourcePurgeEnqueuer:
    """Enqueue one deterministic resource.purge Task per expired Trashed
    Resource (retention elapses trashed_at + RETENTION_DAYS)."""

    RETENTION_DAYS = 7

    def __init__(self, session: AsyncSession, create_task: Any) -> None:
        self._session = session
        self._create_task = create_task

    async def enqueue(self, limit: int = 50) -> int:
        rows = (
            (
                await self._session.execute(
                    text(
                        "SELECT resource_id FROM core.resources "
                        "WHERE lifecycle='Trashed' "
                        "AND trashed_at < now() - make_interval(days => :days) "
                        "ORDER BY trashed_at LIMIT :lim"
                    ),
                    {"days": self.RETENTION_DAYS, "lim": limit},
                )
            )
            .mappings()
            .all()
        )
        enqueued = 0
        for row in rows:
            resource_id: UUID = row["resource_id"]
            await self._create_task.execute(
                "resource.purge",
                task_id=_purge_task_id(resource_id),
                input_ref=str(resource_id),
            )
            enqueued += 1
        return enqueued
