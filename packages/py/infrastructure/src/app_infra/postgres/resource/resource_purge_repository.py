from __future__ import annotations

from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

_DEPENDENT_TABLES = (
    "collab.ai_changesets",
    "collab.resource_comments",
    "collab.resource_assets",
    "collab.resource_search_index",
    "collab.resource_named_versions",
    "collab.resource_checkpoints",
    "collab.resource_update_journal",
    "collab.resource_ownership",
)


class PostgresResourcePurgeRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def purge_resource(self, resource_id: UUID) -> bool:
        exists = await self._session.scalar(
            text("SELECT 1 FROM core.resources WHERE resource_id=:id"),
            {"id": resource_id},
        )
        if exists is None:
            return False
        for table in _DEPENDENT_TABLES:
            await self._session.execute(
                text(f"DELETE FROM {table} WHERE resource_id=:id"),
                {"id": resource_id},
            )
        await self._session.execute(
            text("DELETE FROM core.resources WHERE resource_id=:id"),
            {"id": resource_id},
        )
        return True
