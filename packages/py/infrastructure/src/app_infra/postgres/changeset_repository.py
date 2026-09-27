from __future__ import annotations

import json
from datetime import datetime
from typing import Any
from uuid import UUID

from app_core.ai.domain import ChangeSet, ChangesetStatus
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


class PostgresChangeSetRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def save(self, changeset: ChangeSet) -> ChangeSet:
        row = (
            (
                await self._session.execute(
                    text(
                        "INSERT INTO collab.ai_changesets "
                        "(changeset_id,resource_id,task_id,instruction,status,"
                        "ops,created_by,base_journal_seq) "
                        "VALUES (:cid,:rid,:tid,:inst,:status,:ops,:by,:base_seq) "
                        "RETURNING *"
                    ),
                    {
                        "cid": changeset.changeset_id,
                        "rid": changeset.resource_id,
                        "tid": changeset.task_id,
                        "inst": changeset.instruction,
                        "status": changeset.status.value,
                        "ops": json.dumps(changeset.ops, default=str),
                        "by": changeset.created_by,
                        "base_seq": changeset.base_journal_seq,
                    },
                )
            )
            .mappings()
            .one()
        )
        return _to_changeset(row)

    async def find_by_id(self, changeset_id: UUID) -> ChangeSet | None:
        row = (
            (
                await self._session.execute(
                    text("SELECT * FROM collab.ai_changesets WHERE changeset_id=:id"),
                    {"id": changeset_id},
                )
            )
            .mappings()
            .one_or_none()
        )
        return None if row is None else _to_changeset(row)

    async def mark_applied(
        self,
        changeset_id: UUID,
        *,
        applied_at: datetime,
        journal_seq: int,
    ) -> None:
        await self._session.execute(
            text(
                "UPDATE collab.ai_changesets SET status='Applied',"
                "applied_at=:at,applied_journal_seq=:seq WHERE changeset_id=:id"
            ),
            {"at": applied_at, "seq": journal_seq, "id": changeset_id},
        )


def _to_changeset(row: Any) -> ChangeSet:
    return ChangeSet(
        changeset_id=row["changeset_id"],
        resource_id=row["resource_id"],
        instruction=row["instruction"],
        status=ChangesetStatus(row["status"]),
        ops=list(row["ops"] or []),
        task_id=row["task_id"],
        created_by=row["created_by"],
        created_at=row["created_at"],
        applied_at=row["applied_at"],
        base_journal_seq=row.get("base_journal_seq"),
        applied_journal_seq=row.get("applied_journal_seq"),
    )
