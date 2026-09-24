from __future__ import annotations

from datetime import datetime
from uuid import UUID

from app_core.workspace.ports.purge import (
    PurgeCandidate,
    PurgeDisposition,
    PurgeResult,
    WorkspaceMembershipCleanupPort,
)
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


class PostgresWorkspacePurgeRepository:
    def __init__(
        self,
        session: AsyncSession,
        membership_cleanup: WorkspaceMembershipCleanupPort,
    ) -> None:
        self._session = session
        self._membership_cleanup = membership_cleanup

    async def candidates_before(
        self, now: datetime, limit: int
    ) -> list[PurgeCandidate]:
        result = await self._session.execute(
            text(
                "SELECT workspace_id,purge_eligible_at FROM core.workspaces "
                "WHERE status='DeletionPending' AND purge_eligible_at<=:now "
                "ORDER BY purge_eligible_at,workspace_id LIMIT :limit"
            ),
            {"now": now, "limit": limit},
        )
        return [
            PurgeCandidate(row["workspace_id"], row["purge_eligible_at"])
            for row in result.mappings().all()
        ]

    async def get_for_purge(self, workspace_id: UUID) -> PurgeCandidate | None:
        row = (
            (
                await self._session.execute(
                    text(
                        "SELECT workspace_id,purge_eligible_at FROM core.workspaces "
                        "WHERE workspace_id=:id AND status='DeletionPending' "
                        "AND purge_eligible_at<=now() FOR UPDATE"
                    ),
                    {"id": workspace_id},
                )
            )
            .mappings()
            .one_or_none()
        )
        if row is None:
            return None
        return PurgeCandidate(row["workspace_id"], row["purge_eligible_at"])

    async def purge_workspace(self, workspace_id: UUID) -> PurgeResult:
        candidate = await self.get_for_purge(workspace_id)
        if candidate is None:
            exists = await self._session.scalar(
                text("SELECT 1 FROM core.workspaces WHERE workspace_id=:id"),
                {"id": workspace_id},
            )
            disposition = (
                PurgeDisposition.ALREADY_PURGED
                if exists is None
                else PurgeDisposition.MISSING
            )
            return PurgeResult(workspace_id, disposition)
        await self._membership_cleanup.remove_workspace_memberships(workspace_id)
        folders = await self._session.execute(
            text(
                "DELETE FROM core.folders WHERE project_id IN "
                "(SELECT project_id FROM core.projects WHERE workspace_id=:id)"
            ),
            {"id": workspace_id},
        )
        projects = await self._session.execute(
            text("DELETE FROM core.projects WHERE workspace_id=:id"),
            {"id": workspace_id},
        )
        await self._session.execute(
            text(
                "DELETE FROM core.workspaces WHERE workspace_id=:id "
                "AND status='DeletionPending' AND purge_eligible_at<=now()"
            ),
            {"id": workspace_id},
        )
        return PurgeResult(
            workspace_id,
            PurgeDisposition.PURGED,
            deleted_projects=getattr(projects, "rowcount", 0),
            deleted_folders=getattr(folders, "rowcount", 0),
        )
