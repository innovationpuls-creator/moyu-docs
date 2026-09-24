from __future__ import annotations

from typing import Any
from uuid import UUID, uuid5

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

_NAMESPACE = UUID("6f3c9f7b-8d3c-4d1f-9d6b-c8c1b3d2e4f5")


def _checkpoint_task_id(resource_id: UUID) -> UUID:
    return uuid5(_NAMESPACE, f"resource.checkpoint:{resource_id}")


class PostgresResourceCheckpointEnqueuer:
    """Enqueue one deterministic resource.checkpoint Task per eligible resource.

    Eligible: resource has journal entries and the latest durable journal seq is
    at or beyond the provided threshold. Queue is a trigger only; PostgreSQL is
    authoritative (TaskCreate idempotency collapses duplicates).
    """

    def __init__(self, session: AsyncSession, create_task: Any) -> None:
        self._session = session
        self._create_task = create_task

    async def enqueue(self, threshold: int = 100, limit: int = 50) -> int:
        rows = (
            (
                await self._session.execute(
                    text(
                        "SELECT r.resource_id, MAX(j.journal_seq) AS last_seq "
                        "FROM core.resources r "
                        "JOIN collab.resource_update_journal j "
                        "ON j.resource_id=r.resource_id "
                        "WHERE r.lifecycle='Active' "
                        "GROUP BY r.resource_id HAVING MAX(j.journal_seq)>=:thr "
                        "ORDER BY last_seq LIMIT :lim"
                    ),
                    {"thr": threshold, "lim": limit},
                )
            )
            .mappings()
            .all()
        )
        enqueued = 0
        for row in rows:
            resource_id: UUID = row["resource_id"]
            task_id = _checkpoint_task_id(resource_id)
            await self._create_task.execute(
                "resource.checkpoint",
                task_id=task_id,
                input_ref=str(resource_id),
            )
            enqueued += 1
        return enqueued
