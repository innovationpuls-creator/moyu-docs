from __future__ import annotations

from typing import Any
from uuid import UUID, uuid4

from app_core.resource.domain import Resource, ResourceLifecycle
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


class ResourceNameConflictError(ValueError):
    """A sibling Resource already reserves this name (incl. Trashed/Purged)."""


class PostgresResourceRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(
        self,
        resource: Any | None = None,
        *,
        project_id: UUID | None = None,
        resource_type: str | None = None,
        name: str | None = None,
        normalized_name: str | None = None,
        folder_id: UUID | None = None,
        created_by: UUID | None = None,
    ) -> Resource:
        if resource is not None:
            project_id = project_id or resource.project_id
            resource_type = resource_type or str(resource.resource_type)
            name = name or resource.name
            normalized_name = normalized_name or resource.normalized_name
            folder_id = folder_id or resource.folder_id
            created_by = created_by or resource.created_by
        assert project_id is not None and normalized_name is not None
        if await self._sibling_conflict(project_id, normalized_name):
            raise ResourceNameConflictError(name or "")
        resource_id = uuid4()
        row = (
            (
                await self._session.execute(
                    text(
                        "INSERT INTO core.resources "
                        "(resource_id,project_id,folder_id,resource_type,name,"
                        "normalized_name,lifecycle,schema_version,created_by) "
                        "VALUES (:id,:pid,:fid,:type,:name,:nn,'Active','1.0.0',:by) "
                        "RETURNING *"
                    ),
                    {
                        "id": resource_id,
                        "pid": project_id,
                        "fid": folder_id,
                        "type": resource_type,
                        "name": name,
                        "nn": normalized_name,
                        "by": created_by,
                    },
                )
            )
            .mappings()
            .one()
        )
        return _to_resource(row)

    async def list_by_project(
        self, project_id: UUID, *, folder_id: UUID | None = None
    ) -> list[Resource]:
        folder_filter = "folder_id IS NULL"
        params: dict[str, UUID] = {"pid": project_id}
        if folder_id is not None:
            folder_filter = "folder_id=:folder_id"
            params["folder_id"] = folder_id
        rows = (
            (
                await self._session.execute(
                    text(
                        "SELECT * FROM core.resources WHERE project_id=:pid "
                        f"AND {folder_filter} ORDER BY created_at ASC"
                    ),
                    params,
                )
            )
            .mappings()
            .all()
        )
        return [_to_resource(r) for r in rows]

    async def get(self, resource_id: UUID) -> Resource | None:
        row = (
            (
                await self._session.execute(
                    text("SELECT * FROM core.resources WHERE resource_id=:id"),
                    {"id": resource_id},
                )
            )
            .mappings()
            .one_or_none()
        )
        return None if row is None else _to_resource(row)

    async def rename(
        self, resource_id: UUID, name: str, normalized_name: str
    ) -> Resource:
        current = await self.get(resource_id)
        if current is None:
            raise LookupError("resource not found")
        if current.normalized_name != normalized_name and await self._sibling_conflict(
            current.project_id, normalized_name
        ):
            raise ResourceNameConflictError(name)
        row = (
            (
                await self._session.execute(
                    text(
                        "UPDATE core.resources SET name=:name,normalized_name=:nn,"
                        "updated_at=now() WHERE resource_id=:id RETURNING *"
                    ),
                    {"name": name, "nn": normalized_name, "id": resource_id},
                )
            )
            .mappings()
            .one()
        )
        return _to_resource(row)

    async def folder_belongs_to_project(
        self, folder_id: UUID, project_id: UUID
    ) -> bool:
        row = await self._session.execute(
            text(
                "SELECT 1 FROM core.folders "
                "WHERE folder_id=:folder_id AND project_id=:project_id"
            ),
            {"folder_id": folder_id, "project_id": project_id},
        )
        return row.scalar_one_or_none() is not None

    async def set_lifecycle(self, resource_id: UUID, lifecycle: str) -> Resource | None:
        trashed_at = "now()" if lifecycle == "Trashed" else "NULL"
        row = (
            (
                await self._session.execute(
                    text(
                        "UPDATE core.resources SET lifecycle=:lc,"
                        f"trashed_at={trashed_at},"
                        "updated_at=now() WHERE resource_id=:id RETURNING *"
                    ),
                    {"lc": lifecycle, "id": resource_id},
                )
            )
            .mappings()
            .one_or_none()
        )
        return None if row is None else _to_resource(row)

    async def sibling_exists(self, project_id: UUID, normalized_name: str) -> bool:
        return await self._sibling_conflict(project_id, normalized_name)

    async def _sibling_conflict(self, project_id: UUID, normalized_name: str) -> bool:
        value = await self._session.scalar(
            text(
                "SELECT 1 FROM core.resources WHERE project_id=:pid "
                "AND normalized_name=:nn LIMIT 1"
            ),
            {"pid": project_id, "nn": normalized_name},
        )
        return value is not None

    async def list_readable_for_account(
        self, account_id: UUID, *, limit: int = 50
    ) -> list[Resource]:
        """Resources the account can READ: owned resources plus resources of
        workspaces the account belongs to (membership read, arch 13)."""
        rows = (
            (
                await self._session.execute(
                    text(
                        "SELECT DISTINCT r.resource_id, r.project_id, "
                        "r.resource_type, r.name, r.normalized_name, r.lifecycle, "
                        "r.schema_version, r.created_by, r.created_at, "
                        "r.updated_at, r.trashed_at, r.folder_id "
                        "FROM core.resources r "
                        "JOIN core.projects p ON p.project_id=r.project_id "
                        "LEFT JOIN collab.resource_ownership o "
                        "ON o.resource_id=r.resource_id "
                        "LEFT JOIN core.workspace_members wm "
                        "ON wm.workspace_id=p.workspace_id "
                        "WHERE (o.owner_account_id=:aid OR wm.account_id=:aid) "
                        "AND r.lifecycle='Active' "
                        "ORDER BY r.updated_at DESC LIMIT :lim"
                    ),
                    {"aid": account_id, "lim": limit},
                )
            )
            .mappings()
            .all()
        )
        return [_to_resource(r) for r in rows]


def _to_resource(mapping: Any) -> Resource:
    return Resource(
        resource_id=mapping["resource_id"],
        project_id=mapping["project_id"],
        folder_id=mapping["folder_id"],
        resource_type=mapping["resource_type"],
        name=mapping["name"],
        normalized_name=mapping["normalized_name"],
        lifecycle=ResourceLifecycle(mapping["lifecycle"]),
        schema_version=mapping["schema_version"],
        created_by=mapping["created_by"],
        created_at=mapping["created_at"],
        updated_at=mapping["updated_at"],
        trashed_at=mapping["trashed_at"],
    )
