"""Permission-owned read/grant adapter for collab.resource_ownership."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID

from app_core.permission.domain.access_control import (
    PermissionCapability,
    PermissionRole,
    effective_permission,
)
from app_core.resource.ports import ReadOnlyResourceOwnershipPort
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


@dataclass(frozen=True)
class ResourceOwnership:
    resource_id: UUID
    owner_account_id: UUID
    epoch: int
    lease_until: datetime | None


class PostgresResourceOwnershipRepository(ReadOnlyResourceOwnershipPort):
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def grant(
        self, resource_id: UUID, owner_account_id: UUID, *, lease_seconds: int = 3600
    ) -> ResourceOwnership:
        row = (
            (
                await self._session.execute(
                    text(
                        "INSERT INTO collab.resource_ownership "
                        "(resource_id,owner_account_id,epoch,lease_until) "
                        "VALUES (:rid,:acc,1,:lease) ON CONFLICT (resource_id) "
                        "DO UPDATE SET owner_account_id=EXCLUDED.owner_account_id,"
                        "epoch=resource_ownership.epoch+1,lease_until=EXCLUDED.lease_until,"
                        "updated_at=now() RETURNING *"
                    ),
                    {
                        "rid": resource_id,
                        "acc": owner_account_id,
                        "lease": datetime.now(UTC) + timedelta(seconds=lease_seconds),
                    },
                )
            )
            .mappings()
            .one()
        )
        return _to_ownership(row)

    async def authorize(self, actor_id: UUID, scope_id: UUID, operation: str) -> bool:
        capability = {
            "resource.read": PermissionCapability.READ,
            "resource.update": PermissionCapability.EDIT,
            "resource.comment": PermissionCapability.COMMENT,
            "comment.resolve": PermissionCapability.RESOLVE_COMMENT,
            "comment.reopen": PermissionCapability.REOPEN_COMMENT,
            "resource.manage": PermissionCapability.MANAGE,
            "resource.restore": PermissionCapability.MANAGE,
            "resource.purge": PermissionCapability.PURGE,
            "resource.create": PermissionCapability.EDIT,
        }.get(operation)
        if capability is None:
            return False

        if operation == "resource.create":
            row = (
                (
                    await self._session.execute(
                        text(
                            "SELECT p.workspace_id, p.project_id, "
                            "p.lifecycle AS project_lifecycle, "
                            "w.status AS workspace_status, wm.membership_kind, "
                            "pm.role AS project_role, NULL::text AS resource_role "
                            "FROM core.projects p "
                            "JOIN core.workspaces w ON w.workspace_id=p.workspace_id "
                            "LEFT JOIN core.workspace_members wm "
                            "ON wm.workspace_id=p.workspace_id "
                            "AND wm.account_id=:actor_id "
                            "LEFT JOIN core.project_members pm "
                            "ON pm.project_id=p.project_id "
                            "AND pm.account_id=:actor_id "
                            "WHERE p.project_id=:project_id"
                        ),
                        {"project_id": scope_id, "actor_id": actor_id},
                    )
                )
                .mappings()
                .one_or_none()
            )
        else:
            row = (
                (
                    await self._session.execute(
                        text(
                            "SELECT p.workspace_id, p.project_id, "
                            "p.lifecycle AS project_lifecycle, "
                            "r.lifecycle AS resource_lifecycle, "
                            "w.status AS workspace_status, wm.membership_kind, "
                            "pm.role AS project_role, rp.role AS resource_role "
                            "FROM core.resources r "
                            "JOIN core.projects p ON p.project_id=r.project_id "
                            "JOIN core.workspaces w ON w.workspace_id=p.workspace_id "
                            "LEFT JOIN core.workspace_members wm "
                            "ON wm.workspace_id=p.workspace_id "
                            "AND wm.account_id=:actor_id "
                            "LEFT JOIN core.project_members pm "
                            "ON pm.project_id=p.project_id "
                            "AND pm.account_id=:actor_id "
                            "LEFT JOIN core.resource_permissions rp "
                            "ON rp.resource_id=r.resource_id "
                            "AND rp.account_id=:actor_id "
                            "WHERE r.resource_id=:resource_id"
                        ),
                        {"resource_id": scope_id, "actor_id": actor_id},
                    )
                )
                .mappings()
                .one_or_none()
            )
        if row is None:
            return False
        project_role = (
            PermissionRole(row["project_role"])
            if row["project_role"] is not None
            else None
        )
        resource_override = (
            PermissionRole(row["resource_role"])
            if row["resource_role"] is not None
            else None
        )
        permission = effective_permission(
            project_role,
            resource_override,
            workspace_owner=row["membership_kind"] == "Owner",
            workspace_active=row["workspace_status"] == "Active",
            project_active=row["project_lifecycle"] in {"Active", "Archived"},
            project_read_only=row["project_lifecycle"] == "Archived",
            resource_active=(
                operation in {"resource.create", "resource.restore"}
                or row.get("resource_lifecycle") == "Active"
            ),
        )
        return permission.allows(capability)


def _to_ownership(mapping) -> ResourceOwnership:
    return ResourceOwnership(
        resource_id=mapping["resource_id"],
        owner_account_id=mapping["owner_account_id"],
        epoch=mapping["epoch"],
        lease_until=mapping["lease_until"],
    )
