from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from app_core.workspace.domain.project import (
    Project,
    ProjectExtendedLifecycle,
    ProjectName,
)
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


class PostgresProjectRepository:
    """Project metadata adapter that leaves transaction ownership to callers."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def save(self, project: Project) -> None:
        await self._session.execute(
            text(
                "INSERT INTO core.projects "
                "(project_id,workspace_id,name,normalized_name,lifecycle,created_by,"
                "created_at,updated_at) VALUES "
                "(:project_id,:workspace_id,:name,:normalized_name,:lifecycle,"
                ":created_by,:created_at,:updated_at) "
                "ON CONFLICT (project_id) DO UPDATE SET "
                "name=EXCLUDED.name, normalized_name=EXCLUDED.normalized_name, "
                "lifecycle=EXCLUDED.lifecycle, updated_at=EXCLUDED.updated_at, "
                "archived_at=CASE WHEN EXCLUDED.lifecycle='Archived' "
                "THEN COALESCE(core.projects.archived_at,EXCLUDED.updated_at) "
                "ELSE NULL END, "
                "trashed_at=CASE WHEN EXCLUDED.lifecycle='Trashed' "
                "THEN COALESCE(core.projects.trashed_at,EXCLUDED.updated_at) "
                "ELSE NULL END"
            ),
            {
                "project_id": project.project_id,
                "workspace_id": project.workspace_id,
                "name": project.name.display,
                "normalized_name": project.name.collision_key,
                "lifecycle": project.lifecycle.value,
                "created_by": project.created_by,
                "created_at": project.created_at or datetime.now(UTC),
                "updated_at": project.updated_at or datetime.now(UTC),
            },
        )

    async def find_by_id(self, project_id: UUID) -> Project | None:
        result = await self._session.execute(
            text(
                "SELECT project_id,workspace_id,name,lifecycle,created_by,created_at,"
                "updated_at FROM core.projects WHERE project_id=:project_id"
            ),
            {"project_id": project_id},
        )
        row = result.mappings().one_or_none()
        return _project_from_row(row) if row is not None else None

    async def list_by_workspace(self, workspace_id: UUID) -> list[Project]:
        result = await self._session.execute(
            text(
                "SELECT project_id,workspace_id,name,lifecycle,created_by,created_at,"
                "updated_at FROM core.projects WHERE workspace_id=:workspace_id "
                "ORDER BY created_at,project_id"
            ),
            {"workspace_id": workspace_id},
        )
        return [_project_from_row(row) for row in result.mappings()]

    async def list_name_reservations(self, workspace_id: UUID) -> list[Project]:
        result = await self._session.execute(
            text(
                "SELECT project_id,workspace_id,name,lifecycle,created_by,created_at,"
                "updated_at FROM core.projects WHERE workspace_id=:workspace_id"
            ),
            {"workspace_id": workspace_id},
        )
        return [_project_from_row(row) for row in result.mappings()]


def _project_from_row(row) -> Project:
    return Project(
        project_id=row["project_id"],
        workspace_id=row["workspace_id"],
        name=ProjectName(row["name"]),
        lifecycle=ProjectExtendedLifecycle(row["lifecycle"]),
        created_by=row["created_by"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )
