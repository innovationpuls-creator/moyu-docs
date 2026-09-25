from __future__ import annotations

from uuid import UUID

from app_core.resource.purge import ResourcePermissionBindingCleanupPort
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


class PostgresPermissionResourceCleanupRepository(ResourcePermissionBindingCleanupPort):
    """Delete Permission-owned bindings before Resource metadata is purged."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def remove_resource_permission_bindings(self, resource_id: UUID) -> None:
        for table in (
            "core.invitations",
            "core.resource_permissions",
            "core.share_links",
            "collab.resource_ownership",
        ):
            await self._session.execute(
                text(f"DELETE FROM {table} WHERE resource_id=:resource_id"),
                {"resource_id": resource_id},
            )
