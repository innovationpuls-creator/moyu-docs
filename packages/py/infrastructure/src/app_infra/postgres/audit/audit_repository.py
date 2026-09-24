from __future__ import annotations

import json
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


class PostgresAuditRepository:
    """Append-only audit trail (arch 23 audit category); rows are NEVER
    updated/deleted by application code."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def record(
        self,
        *,
        actor_account_id: UUID | None,
        action: str,
        target_type: str,
        target_id: UUID | None,
        detail: dict[str, Any] | None = None,
    ) -> None:
        await self._session.execute(
            text(
                "INSERT INTO core.audit_entries "
                "(entry_id,actor_account_id,action,target_type,target_id,detail) "
                "VALUES (:eid,:actor,:action,:ttype,:tid,:detail)"
            ),
            {
                "eid": uuid4(),
                "actor": actor_account_id,
                "action": action,
                "ttype": target_type,
                "tid": target_id,
                "detail": json.dumps(detail) if detail else None,
            },
        )
