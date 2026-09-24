from __future__ import annotations

from uuid import UUID

from app_core.resource.domain import JournalOp
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


class DuplicateJournalSeqError(ValueError):
    """The given journal sequence is already durably present for this resource."""


class MissingJournalSeqError(ValueError):
    """The requested cursor position does not exist for this resource."""


class PostgresJournalRepository:
    """Append-only update journal for a resource (arch 06 §7, arch 29 §46)."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def append_op(
        self,
        resource_id: UUID,
        journal_seq: int,
        ownership_epoch: int,
        update_bytes: bytes,
        update_hash: str,
    ) -> JournalOp:
        result = await self._session.execute(
            text(
                "INSERT INTO collab.resource_update_journal "
                "(resource_id,journal_seq,ownership_epoch,update_bytes,update_hash) "
                "VALUES (:rid,:seq,:epoch,:bytes,:hash) ON CONFLICT DO NOTHING "
                "RETURNING resource_id,journal_seq,ownership_epoch,update_bytes,"
                "update_hash,accepted_at,durable_at"
            ),
            {
                "rid": resource_id,
                "seq": journal_seq,
                "epoch": ownership_epoch,
                "bytes": bytes(update_bytes),
                "hash": update_hash,
            },
        )
        row = result.mappings().one_or_none()
        if row is None:
            raise DuplicateJournalSeqError(
                f"journal_seq {journal_seq} already present for {resource_id}"
            )
        return JournalOp(
            resource_id=row["resource_id"],
            journal_seq=row["journal_seq"],
            ownership_epoch=row["ownership_epoch"],
            update_bytes=bytes(row["update_bytes"]),
            update_hash=row["update_hash"],
            accepted_at=row["accepted_at"],
            durable_at=row["durable_at"],
        )

    async def mark_durable(self, resource_id: UUID, journal_seq: int) -> None:
        await self._session.execute(
            text(
                "UPDATE collab.resource_update_journal SET durable_at=now() "
                "WHERE resource_id=:rid AND journal_seq=:seq AND durable_at IS NULL"
            ),
            {"rid": resource_id, "seq": journal_seq},
        )

    async def read_cursor(
        self, resource_id: UUID, after_seq: int, *, limit: int = 200
    ) -> list[JournalOp]:
        rows = (
            (
                await self._session.execute(
                    text(
                        "SELECT resource_id,journal_seq,ownership_epoch,update_bytes,"
                        "update_hash,accepted_at,durable_at FROM "
                        "collab.resource_update_journal "
                        "WHERE resource_id=:rid AND journal_seq>:after "
                        "ORDER BY journal_seq LIMIT :limit"
                    ),
                    {"rid": resource_id, "after": after_seq, "limit": limit},
                )
            )
            .mappings()
            .all()
        )
        return [
            JournalOp(
                resource_id=r["resource_id"],
                journal_seq=r["journal_seq"],
                ownership_epoch=r["ownership_epoch"],
                update_bytes=bytes(r["update_bytes"]),
                update_hash=r["update_hash"],
                accepted_at=r["accepted_at"],
                durable_at=r["durable_at"],
            )
            for r in rows
        ]

    async def max_seq(self, resource_id: UUID) -> int:
        value = await self._session.scalar(
            text(
                "SELECT COALESCE(MAX(journal_seq),0) FROM "
                "collab.resource_update_journal WHERE resource_id=:rid"
            ),
            {"rid": resource_id},
        )
        return int(value or 0)
