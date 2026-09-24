from __future__ import annotations

from uuid import UUID

from app_core.workspace.application.use_cases import Workspace
from app_core.workspace.domain.lifecycle import WorkspaceLifecycle
from app_core.workspace.domain.name import WorkspaceName
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


class PostgresWorkspaceRepository:
    """Persist Workspace metadata in the caller's transaction."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def save(self, workspace: Workspace) -> None:
        await self._session.execute(
            text(
                "INSERT INTO core.workspaces "
                "(workspace_id, name, created_by, created_at, updated_at, status) "
                "VALUES (:workspace_id, :name, :created_by, :created_at, "
                ":updated_at, :status)"
            ),
            {
                "workspace_id": workspace.workspace_id,
                "name": workspace.name.display,
                "created_by": workspace.created_by,
                "created_at": workspace.created_at,
                "updated_at": workspace.updated_at,
                "status": workspace.lifecycle.value,
            },
        )

    async def find_by_id(self, workspace_id: UUID) -> Workspace | None:
        result = await self._session.execute(
            text(
                "SELECT workspace_id, name, created_by, created_at, updated_at, status "
                "FROM core.workspaces "
                "WHERE workspace_id = :workspace_id AND status <> 'Deleted'"
            ),
            {"workspace_id": workspace_id},
        )
        row = result.mappings().one_or_none()
        if row is None:
            return None
        return Workspace(
            row["workspace_id"],
            WorkspaceName(row["name"]),
            row["created_by"],
            row["created_at"],
            row["updated_at"],
            WorkspaceLifecycle(row["status"]),
        )
