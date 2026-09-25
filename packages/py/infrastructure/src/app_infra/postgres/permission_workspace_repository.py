from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from app_core.common.exceptions import (
    ConflictError,
    IdempotencyConflictError,
    NotFoundError,
    PermissionDeniedError,
)
from app_core.permission.domain.access_control import (
    PermissionCapability,
    PermissionRole,
    effective_permission,
)
from app_core.permission.domain.workspace_membership import (
    PermissionDependencyError,
    WorkspaceOperation,
    WorkspaceOwnerTransferResult,
)
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app_infra.postgres.permission_event_publisher import (
    publish_permission_changed,
)


class PostgresWorkspaceMembershipRepository:
    """Permission-owned membership writes using the caller's transaction."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def grant_initial_owner(self, workspace_id: UUID, account_id: UUID) -> None:
        workspace_status = await self._session.scalar(
            text(
                "SELECT status FROM core.workspaces WHERE workspace_id=:id FOR UPDATE"
            ),
            {"id": workspace_id},
        )
        if workspace_status is None:
            raise NotFoundError("Workspace not found.", "WORKSPACE_NOT_FOUND")
        if workspace_status != "Active":
            raise ConflictError(
                "Workspace is not active for initial Owner creation.",
                "WORKSPACE_LIFECYCLE_CONFLICT",
            )

        account_status = await self._session.scalar(
            text("SELECT status FROM auth.accounts WHERE account_id=:id FOR UPDATE"),
            {"id": account_id},
        )
        if account_status != "Active":
            raise PermissionDeniedError(
                "Only Active Accounts can create a Workspace.",
                "WORKSPACE_CREATION_REQUIRES_ACTIVE_ACCOUNT",
            )

        await self._session.execute(
            text(
                "INSERT INTO core.workspace_members "
                "(workspace_id, account_id, membership_kind) "
                "VALUES (:workspace_id, :account_id, 'Owner')"
            ),
            {"workspace_id": workspace_id, "account_id": account_id},
        )

    async def transfer_owner_idempotently(
        self,
        actor_id: UUID,
        workspace_id: UUID,
        new_owner_id: UUID,
        idempotency_key: str,
    ) -> WorkspaceOwnerTransferResult:
        key = f"workspace-owner-transfer:{idempotency_key}"
        request_hash = hashlib.sha256(
            f"{workspace_id}:{actor_id}:{new_owner_id}".encode()
        ).hexdigest()
        workspace_status = await self._session.scalar(
            text(
                "SELECT status FROM core.workspaces WHERE workspace_id=:id FOR UPDATE"
            ),
            {"id": workspace_id},
        )
        if workspace_status is None or workspace_status == "Deleted":
            raise NotFoundError("Workspace not found.", "WORKSPACE_NOT_FOUND")

        claimed = await self._session.scalar(
            text(
                "INSERT INTO integration.idempotency_records (idempotency_key) "
                "VALUES (:key) ON CONFLICT (idempotency_key) DO NOTHING "
                "RETURNING idempotency_key"
            ),
            {"key": key},
        )
        if claimed is None:
            response = await self._session.scalar(
                text(
                    "SELECT response FROM integration.idempotency_records "
                    "WHERE idempotency_key=:key FOR UPDATE"
                ),
                {"key": key},
            )
            if response is None:
                raise IdempotencyConflictError(
                    "Idempotency key is already in progress.",
                    "IDEMPOTENCY_KEY_CONFLICT",
                )
            record = json.loads(response)
            if record["request_hash"] != request_hash:
                raise IdempotencyConflictError(
                    "Idempotency key was used for a different owner transfer.",
                    "IDEMPOTENCY_KEY_CONFLICT",
                )
            return _transfer_result(record["result"])

        owner_row = (
            await self._session.execute(
                text(
                    "SELECT account_id FROM core.workspace_members "
                    "WHERE workspace_id=:workspace_id "
                    "AND membership_kind='Owner' FOR UPDATE"
                ),
                {"workspace_id": workspace_id},
            )
        ).one_or_none()
        if owner_row is None:
            await self._release_idempotency_claim(key)
            status = await self._session.scalar(
                text("SELECT status FROM core.workspaces WHERE workspace_id=:id"),
                {"id": workspace_id},
            )
            if status is not None and status != "Deleted":
                raise PermissionDependencyError("Non-Deleted Workspace has no Owner")
            raise ConflictError(
                "Workspace Owner transfer state is invalid.",
                "WORKSPACE_OWNER_TRANSFER_INVALID",
            )
        if owner_row.account_id != actor_id:
            await self._release_idempotency_claim(key)
            raise ConflictError(
                "Workspace Owner changed before transfer.",
                "WORKSPACE_OWNER_TRANSFER_INVALID",
            )
        if actor_id == new_owner_id:
            await self._release_idempotency_claim(key)
            raise ConflictError(
                "New Owner must differ from current Owner.",
                "WORKSPACE_OWNER_TRANSFER_INVALID",
            )

        target = (
            await self._session.execute(
                text(
                    "SELECT m.account_id FROM core.workspace_members AS m "
                    "JOIN auth.accounts AS a ON a.account_id=m.account_id "
                    "WHERE m.workspace_id=:workspace_id AND m.account_id=:target "
                    "AND m.membership_kind='Member' AND a.status='Active' "
                    "FOR UPDATE OF m, a"
                ),
                {"workspace_id": workspace_id, "target": new_owner_id},
            )
        ).one_or_none()
        if target is None:
            await self._release_idempotency_claim(key)
            raise ConflictError(
                "Workspace Owner transfer target must be an active member.",
                "WORKSPACE_OWNER_TRANSFER_INVALID",
            )

        await self._session.execute(
            text(
                "UPDATE core.workspace_members SET membership_kind='Member' "
                "WHERE workspace_id=:workspace_id AND account_id=:owner"
            ),
            {"workspace_id": workspace_id, "owner": actor_id},
        )
        await self._session.execute(
            text(
                "UPDATE core.workspace_members SET membership_kind='Owner' "
                "WHERE workspace_id=:workspace_id AND account_id=:target"
            ),
            {"workspace_id": workspace_id, "target": new_owner_id},
        )

        transferred_at = datetime.now(UTC)
        result: dict[str, Any] = {
            "workspace_id": str(workspace_id),
            "previous_owner_account_id": str(actor_id),
            "new_owner_account_id": str(new_owner_id),
            "transferred_at": transferred_at.isoformat(),
        }
        response = json.dumps({"request_hash": request_hash, "result": result})
        await self._session.execute(
            text(
                "UPDATE integration.idempotency_records SET response=:response "
                "WHERE idempotency_key=:key"
            ),
            {"key": key, "response": response},
        )
        await self._session.execute(
            text(
                "INSERT INTO audit.entries "
                "(audit_id, actor_type, actor_id, action, workspace_id, "
                "target_ref, metadata) "
                "VALUES (:id, 'Account', :actor, 'WorkspaceOwnerTransferred', "
                ":workspace_id, "
                "CAST(:target_ref AS jsonb), CAST(:metadata AS jsonb))"
            ),
            {
                "id": uuid4(),
                "actor": actor_id,
                "workspace_id": workspace_id,
                "target_ref": json.dumps({"accountId": str(new_owner_id)}),
                "metadata": json.dumps({"previousOwnerAccountId": str(actor_id)}),
            },
        )
        await self._publish_owner_transfer_permissions(
            workspace_id, actor_id, new_owner_id
        )
        return _transfer_result(result)

    async def _publish_owner_transfer_permissions(
        self, workspace_id: UUID, previous_owner_id: UUID, new_owner_id: UUID
    ) -> None:
        for account_id, role in (
            (previous_owner_id, "Member"),
            (new_owner_id, "Owner"),
        ):
            await publish_permission_changed(
                self._session,
                scope_type="workspace",
                scope_id=workspace_id,
                workspace_id=workspace_id,
                account_id=account_id,
                action="owner_transferred",
                role=role,
            )

    async def _release_idempotency_claim(self, key: str) -> None:
        await self._session.execute(
            text(
                "DELETE FROM integration.idempotency_records "
                "WHERE idempotency_key=:key AND response IS NULL"
            ),
            {"key": key},
        )

    async def authorize(
        self,
        actor_id: UUID,
        operation: WorkspaceOperation,
        *,
        workspace_id: UUID,
        project_id: UUID | None = None,
    ) -> None:
        if not isinstance(operation, WorkspaceOperation):
            raise PermissionDeniedError("Unknown Workspace operation.")
        if operation is WorkspaceOperation.CREATE:
            raise PermissionDeniedError(
                "Workspace creation authorization is not defined here."
            )
        await self._require_active_workspace(workspace_id)
        if project_id is None:
            membership_kind = await self._workspace_membership_kind(
                actor_id, workspace_id
            )
            self._authorize_workspace_operation(operation, membership_kind)
            return
        await self._authorize_project_operation(
            actor_id, operation, workspace_id, project_id
        )

    async def _require_active_workspace(self, workspace_id: UUID) -> None:
        status = await self._session.scalar(
            text("SELECT status FROM core.workspaces WHERE workspace_id=:id"),
            {"id": workspace_id},
        )
        if status != "Active":
            raise PermissionDeniedError("Workspace access is unavailable.")

    async def _workspace_membership_kind(
        self, actor_id: UUID, workspace_id: UUID
    ) -> str | None:
        return await self._session.scalar(
            text(
                "SELECT membership_kind FROM core.workspace_members "
                "WHERE workspace_id=:workspace_id AND account_id=:actor_id"
            ),
            {"workspace_id": workspace_id, "actor_id": actor_id},
        )

    @staticmethod
    def _authorize_workspace_operation(
        operation: WorkspaceOperation, membership_kind: str | None
    ) -> None:
        if membership_kind is not None and operation is WorkspaceOperation.READ:
            return
        if membership_kind == "Owner" and operation in {
            WorkspaceOperation.MANAGE,
            WorkspaceOperation.TRASH,
            WorkspaceOperation.RESTORE,
            WorkspaceOperation.PURGE,
        }:
            return
        raise PermissionDeniedError("Workspace operation is not permitted.")

    async def _authorize_project_operation(
        self,
        actor_id: UUID,
        operation: WorkspaceOperation,
        workspace_id: UUID,
        project_id: UUID,
    ) -> None:
        project_workspace = await self._session.execute(
            text("SELECT workspace_id FROM core.projects WHERE project_id=:project_id"),
            {"project_id": project_id},
        )
        project_row = project_workspace.mappings().one_or_none()
        if project_row is None or project_row["workspace_id"] != workspace_id:
            raise PermissionDeniedError("Project is outside the requested Workspace.")

        workspace_owner = (
            await self._workspace_membership_kind(actor_id, workspace_id) == "Owner"
        )
        project_role = await self._session.scalar(
            text(
                "SELECT role FROM core.project_members "
                "WHERE project_id=:project_id AND account_id=:actor_id"
            ),
            {"project_id": project_id, "actor_id": actor_id},
        )
        effective = effective_permission(
            PermissionRole(project_role) if project_role is not None else None,
            workspace_owner=workspace_owner,
        )
        capability = {
            WorkspaceOperation.READ: PermissionCapability.READ,
            WorkspaceOperation.MANAGE: PermissionCapability.MANAGE,
            WorkspaceOperation.TRASH: PermissionCapability.MANAGE,
            WorkspaceOperation.RESTORE: PermissionCapability.MANAGE,
            WorkspaceOperation.PURGE: PermissionCapability.PURGE,
        }.get(operation)
        if capability is not None and effective.allows(capability):
            return
        raise PermissionDeniedError(
            "Project operation is not permitted.", "WORKSPACE_PERMISSION_DENIED"
        )

    async def can_manage_project(self, account_id: UUID, project_id: UUID) -> bool:
        result = await self._session.scalar(
            text(
                "SELECT EXISTS ("
                "SELECT 1 FROM core.projects AS p "
                "JOIN core.workspace_members AS m "
                "ON m.workspace_id=p.workspace_id "
                "WHERE p.project_id=:project_id AND m.account_id=:account_id "
                "AND m.membership_kind='Owner'"
                ")"
            ),
            {"project_id": project_id, "account_id": account_id},
        )
        return bool(result)

    async def find_account(self, account_id: UUID) -> Any | None:
        row = (
            (
                await self._session.execute(
                    text(
                        "SELECT account_id, status FROM auth.accounts "
                        "WHERE account_id=:id"
                    ),
                    {"id": account_id},
                )
            )
            .mappings()
            .one_or_none()
        )
        if row is None:
            return None
        return _AccountStatusProjection(row["account_id"], row["status"])

    async def sole_owned_workspace(
        self, account_id: UUID
    ) -> tuple[bool, str | None, UUID | None]:
        rows = (
            await self._session.execute(
                text(
                    "SELECT w.workspace_id, w.name FROM core.workspaces AS w "
                    "JOIN core.workspace_members AS m ON m.workspace_id=w.workspace_id "
                    "WHERE m.account_id=:account_id AND m.membership_kind='Owner' "
                    "AND w.status <> 'Deleted' ORDER BY w.workspace_id"
                ),
                {"account_id": account_id},
            )
        ).all()
        if not rows:
            return False, None, None
        first = rows[0]
        return True, first.name, first.workspace_id

    async def has_sole_ownership(self, account_id: UUID) -> tuple[bool, str | None]:
        is_sole, name, _ = await self.sole_owned_workspace(account_id)
        if not is_sole:
            return False, None
        if (
            len(
                (
                    await self._session.execute(
                        text(
                            "SELECT w.workspace_id FROM core.workspaces AS w "
                            "JOIN core.workspace_members AS m "
                            "ON m.workspace_id=w.workspace_id "
                            "WHERE m.account_id=:account_id "
                            "AND m.membership_kind='Owner' "
                            "AND w.status <> 'Deleted'"
                        ),
                        {"account_id": account_id},
                    )
                ).all()
            )
            > 1
        ):
            return True, None
        return True, name

    async def get_current_workspace_owner(self, workspace_id: UUID) -> UUID | None:
        workspace = (
            await self._session.execute(
                text("SELECT status FROM core.workspaces WHERE workspace_id=:id"),
                {"id": workspace_id},
            )
        ).scalar_one_or_none()
        if workspace is None or workspace == "Deleted":
            return None
        owners = (
            (
                await self._session.execute(
                    text(
                        "SELECT account_id FROM core.workspace_members "
                        "WHERE workspace_id=:id AND membership_kind='Owner'"
                    ),
                    {"id": workspace_id},
                )
            )
            .scalars()
            .all()
        )
        if len(owners) != 1:
            raise PermissionDependencyError(
                "Non-Deleted Workspace Owner state is invalid"
            )
        return owners[0]

    async def remove_workspace_memberships(self, workspace_id: UUID) -> None:
        await self._session.execute(
            text("DELETE FROM core.invitations WHERE workspace_id=:workspace_id"),
            {"workspace_id": workspace_id},
        )
        await self._session.execute(
            text(
                "DELETE FROM core.project_members WHERE project_id IN "
                "(SELECT project_id FROM core.projects "
                "WHERE workspace_id=:workspace_id)"
            ),
            {"workspace_id": workspace_id},
        )
        await self._session.execute(
            text("DELETE FROM core.workspace_members WHERE workspace_id=:workspace_id"),
            {"workspace_id": workspace_id},
        )

    async def list_workspaces_for_account(
        self, account_id: UUID
    ) -> list[tuple[UUID, str, str, str]]:
        """(workspace_id, name, membership_kind, lifecycle) for the account."""
        rows = (
            (
                await self._session.execute(
                    text(
                        "SELECT w.workspace_id, w.name, wm.membership_kind, w.status "
                        "FROM core.workspace_members wm "
                        "JOIN core.workspaces w ON w.workspace_id=wm.workspace_id "
                        "WHERE wm.account_id=:acc ORDER BY w.created_at DESC"
                    ),
                    {"acc": account_id},
                )
            )
            .mappings()
            .all()
        )
        return [
            (r["workspace_id"], r["name"], r["membership_kind"], r["status"])
            for r in rows
        ]

    async def add_member(self, workspace_id: UUID, account_id: UUID) -> None:
        await self._session.execute(
            text(
                "SELECT workspace_id FROM core.workspaces "
                "WHERE workspace_id=:id FOR UPDATE"
            ),
            {"id": workspace_id},
        )
        await self._session.execute(
            text(
                "INSERT INTO core.workspace_members "
                "(workspace_id, account_id, membership_kind) "
                "VALUES (:workspace_id, :account_id, 'Member')"
            ),
            {"workspace_id": workspace_id, "account_id": account_id},
        )


class _AccountStatusProjection:
    def __init__(self, account_id: UUID, status: str) -> None:
        self.account_id = account_id
        self.status = status


def _transfer_result(value: dict[str, Any]) -> WorkspaceOwnerTransferResult:
    return WorkspaceOwnerTransferResult(
        workspace_id=UUID(value["workspace_id"]),
        previous_owner_account_id=UUID(value["previous_owner_account_id"]),
        new_owner_account_id=UUID(value["new_owner_account_id"]),
        transferred_at=datetime.fromisoformat(value["transferred_at"]),
    )
