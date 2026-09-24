from __future__ import annotations

from typing import Any
from uuid import UUID

from app_core.resource.domain import Checkpoint
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


class PostgresCheckpointRepository:
    """Materialized state snapshots + safe journal truncation (arch 06 §10-14)."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def write(
        self,
        resource_id: UUID,
        base_journal_seq: int,
        snapshot: dict[str, Any],
        created_by: UUID | None = None,
    ) -> Checkpoint:
        checkpoint_seq = int(
            (
                await self._session.scalar(
                    text(
                        "SELECT COALESCE(MAX(checkpoint_seq),0)+1 FROM "
                        "collab.resource_checkpoints WHERE resource_id=:rid"
                    ),
                    {"rid": resource_id},
                )
            )
            or 1
        )
        row = (
            (
                await self._session.execute(
                    text(
                        "INSERT INTO collab.resource_checkpoints "
                        "(resource_id,checkpoint_seq,base_journal_seq,snapshot,"
                        "created_by) "
                        "VALUES (:rid,:seq,:base,CAST(:snap AS jsonb),:by) RETURNING "
                        "resource_id,checkpoint_seq,base_journal_seq,snapshot,created_at"
                    ),
                    {
                        "rid": resource_id,
                        "seq": checkpoint_seq,
                        "base": base_journal_seq,
                        "snap": __import__("json").dumps(snapshot),
                        "by": created_by,
                    },
                )
            )
            .mappings()
            .one()
        )
        return Checkpoint(
            resource_id=row["resource_id"],
            checkpoint_seq=row["checkpoint_seq"],
            base_journal_seq=row["base_journal_seq"],
            snapshot=dict(row["snapshot"]),
            created_at=row["created_at"],
        )

    async def latest(self, resource_id: UUID) -> Checkpoint | None:
        row = (
            (
                await self._session.execute(
                    text(
                        "SELECT resource_id,checkpoint_seq,base_journal_seq,snapshot,"
                        "created_at FROM collab.resource_checkpoints "
                        "WHERE resource_id=:rid ORDER BY checkpoint_seq DESC LIMIT 1"
                    ),
                    {"rid": resource_id},
                )
            )
            .mappings()
            .one_or_none()
        )
        if row is None:
            return None
        return Checkpoint(
            resource_id=row["resource_id"],
            checkpoint_seq=row["checkpoint_seq"],
            base_journal_seq=row["base_journal_seq"],
            snapshot=dict(row["snapshot"]),
            created_at=row["created_at"],
        )

    async def list_recent(
        self, resource_id: UUID, *, limit: int = 10
    ) -> list[Checkpoint]:
        rows = (
            (
                await self._session.execute(
                    text(
                        "SELECT * FROM collab.resource_checkpoints "
                        "WHERE resource_id=:rid ORDER BY checkpoint_seq DESC "
                        "LIMIT :lim"
                    ),
                    {"rid": resource_id, "lim": limit},
                )
            )
            .mappings()
            .all()
        )
        return [
            Checkpoint(
                resource_id=r["resource_id"],
                checkpoint_seq=r["checkpoint_seq"],
                base_journal_seq=r["base_journal_seq"],
                snapshot=dict(r["snapshot"]),
                created_at=r["created_at"],
            )
            for r in rows
        ]

    async def truncate_before(self, resource_id: UUID, journal_seq: int) -> int:
        """Delete journal rows <= journal_seq (caller verified the checkpoint)."""
        result = await self._session.execute(
            text(
                "DELETE FROM collab.resource_update_journal "
                "WHERE resource_id=:rid AND journal_seq<=:seq"
            ),
            {"rid": resource_id, "seq": journal_seq},
        )
        return result.rowcount  # type: ignore[attr-defined]
