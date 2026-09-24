from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from app_core.common.exceptions import ConflictError
from app_core.workspace.domain.folder import (
    Folder,
    FolderExtendedLifecycle,
    FolderName,
)
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


class PostgresFolderRepository:
    """Folder metadata adapter that leaves transaction ownership to callers."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def save(self, folder: Folder) -> None:
        await self._lock_project(folder.project_id)
        await self._validate_parent(folder.project_id, folder.parent_folder_id)
        await self._session.execute(
            text(
                "INSERT INTO core.folders "
                "(folder_id,project_id,parent_folder_id,name,normalized_name,lifecycle,"
                "created_at,updated_at) VALUES "
                "(:folder_id,:project_id,:parent_folder_id,:name,:normalized_name,"
                ":lifecycle,:created_at,:updated_at) "
                "ON CONFLICT (folder_id) DO UPDATE SET "
                "parent_folder_id=EXCLUDED.parent_folder_id, name=EXCLUDED.name, "
                "normalized_name=EXCLUDED.normalized_name, "
                "lifecycle=EXCLUDED.lifecycle, updated_at=EXCLUDED.updated_at"
            ),
            {
                "folder_id": folder.folder_id,
                "project_id": folder.project_id,
                "parent_folder_id": folder.parent_folder_id,
                "name": folder.name.display,
                "normalized_name": folder.name.collision_key,
                "lifecycle": folder.lifecycle.value,
                "created_at": folder.created_at or datetime.now(UTC),
                "updated_at": folder.updated_at or datetime.now(UTC),
            },
        )

    async def find_by_id(self, folder_id: UUID) -> Folder | None:
        result = await self._session.execute(
            text(
                "SELECT folder_id,project_id,parent_folder_id,name,lifecycle,"
                "created_at,"
                "updated_at FROM core.folders WHERE folder_id=:folder_id"
            ),
            {"folder_id": folder_id},
        )
        row = result.mappings().one_or_none()
        return _folder_from_row(row) if row is not None else None

    async def list_by_project(self, project_id: UUID) -> list[Folder]:
        result = await self._session.execute(
            text(
                "SELECT folder_id,project_id,parent_folder_id,name,lifecycle,"
                "created_at,"
                "updated_at FROM core.folders WHERE project_id=:project_id "
                "ORDER BY created_at,folder_id"
            ),
            {"project_id": project_id},
        )
        return [_folder_from_row(row) for row in result.mappings()]

    async def list_name_reservations(
        self, project_id: UUID, parent_folder_id: UUID | None
    ) -> list[Folder]:
        result = await self._session.execute(
            text(
                "SELECT folder_id,project_id,parent_folder_id,name,lifecycle,"
                "created_at,"
                "updated_at FROM core.folders WHERE project_id=:project_id "
                "AND parent_folder_id IS NOT DISTINCT FROM :parent_folder_id"
            ),
            {"project_id": project_id, "parent_folder_id": parent_folder_id},
        )
        return [_folder_from_row(row) for row in result.mappings()]

    async def get_ancestors(self, folder_id: UUID) -> list[Folder]:
        result = await self._session.execute(
            text(
                "WITH RECURSIVE ancestors AS ("
                "SELECT f.folder_id,f.project_id,f.parent_folder_id,f.name,f.lifecycle,"
                "f.created_at,f.updated_at FROM core.folders AS start "
                "JOIN core.folders AS f ON f.folder_id=start.parent_folder_id "
                "WHERE start.folder_id=:folder_id UNION ALL "
                "SELECT p.folder_id,p.project_id,p.parent_folder_id,p.name,p.lifecycle,"
                "p.created_at,p.updated_at FROM core.folders AS p "
                "JOIN ancestors AS a ON p.folder_id=a.parent_folder_id) "
                "SELECT * FROM ancestors"
            ),
            {"folder_id": folder_id},
        )
        return [_folder_from_row(row) for row in result.mappings()]

    async def list_descendant_ids(self, folder_id: UUID) -> set[UUID]:
        project_id = await self._session.scalar(
            text("SELECT project_id FROM core.folders WHERE folder_id=:id"),
            {"id": folder_id},
        )
        if project_id is None:
            return set()
        await self._lock_project(project_id)
        result = await self._session.execute(
            text(
                "WITH RECURSIVE descendants AS ("
                "SELECT folder_id FROM core.folders WHERE parent_folder_id=:folder_id "
                "UNION ALL SELECT f.folder_id FROM core.folders AS f "
                "JOIN descendants AS d ON f.parent_folder_id=d.folder_id) "
                "SELECT folder_id FROM descendants"
            ),
            {"folder_id": folder_id},
        )
        return set(result.scalars())

    async def move(self, folder_id: UUID, parent_folder_id: UUID | None) -> Folder:
        folder = await self.find_by_id(folder_id)
        if folder is None:
            raise ConflictError("Folder is unavailable.", "FOLDER_NOT_FOUND")
        await self._lock_project(folder.project_id)
        await self._validate_parent(folder.project_id, parent_folder_id)
        if parent_folder_id is not None:
            if parent_folder_id == folder_id:
                raise ConflictError("Folder cannot parent itself.", "FOLDER_CYCLE")
            descendants = await self.list_descendant_ids(folder_id)
            if parent_folder_id in descendants:
                raise ConflictError("Folder move would create a cycle.", "FOLDER_CYCLE")
        await self._session.execute(
            text(
                "UPDATE core.folders SET parent_folder_id=:parent,updated_at=now() "
                "WHERE folder_id=:folder_id"
            ),
            {"parent": parent_folder_id, "folder_id": folder_id},
        )
        moved = await self.find_by_id(folder_id)
        if moved is None:
            raise ConflictError("Folder disappeared during move.", "FOLDER_NOT_FOUND")
        return moved

    async def set_lifecycle(
        self, folder_id: UUID, lifecycle: FolderExtendedLifecycle
    ) -> None:
        await self._session.execute(
            text(
                "UPDATE core.folders SET lifecycle=:lifecycle,updated_at=now() "
                "WHERE folder_id=:folder_id"
            ),
            {"lifecycle": lifecycle.value, "folder_id": folder_id},
        )

    async def _lock_project(self, project_id: UUID) -> None:
        await self._session.execute(
            text(
                "SELECT project_id FROM core.projects WHERE project_id=:id FOR UPDATE"
            ),
            {"id": project_id},
        )

    async def _validate_parent(
        self, project_id: UUID, parent_folder_id: UUID | None
    ) -> None:
        if parent_folder_id is None:
            return
        result = await self._session.execute(
            text("SELECT project_id FROM core.folders WHERE folder_id=:id FOR UPDATE"),
            {"id": parent_folder_id},
        )
        parent_project_id = result.scalar_one_or_none()
        if parent_project_id != project_id:
            raise ConflictError(
                "Parent Folder must belong to the same Project.",
                "WORKSPACE_PARENT_INVALID",
            )


def _folder_from_row(row) -> Folder:
    return Folder(
        folder_id=row["folder_id"],
        project_id=row["project_id"],
        parent_folder_id=row["parent_folder_id"],
        name=FolderName(row["name"]),
        lifecycle=FolderExtendedLifecycle(row["lifecycle"]),
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )
