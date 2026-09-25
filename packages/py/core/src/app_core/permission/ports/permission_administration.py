from __future__ import annotations

from datetime import datetime
from typing import Protocol
from uuid import UUID

from app_core.permission.domain.access_control import (
    EffectivePermission,
    PermissionRole,
)
from app_core.permission.domain.collaboration import (
    CreatedWorkspaceInvitation,
    InvitationAcceptanceExpired,
    ProjectMemberView,
    ResourcePermissionView,
    WorkspaceInvitationView,
    WorkspaceMemberView,
)


class PermissionAdministrationRepository(Protocol):
    async def get_resource_capabilities(
        self, actor_id: UUID, resource_id: UUID
    ) -> EffectivePermission | None: ...

    async def create_workspace_invitation(
        self,
        actor_id: UUID,
        workspace_id: UUID,
        target_email: str,
        token_hash: str,
        invitation_url: str,
        expires_at: datetime,
        expires_in_days: int,
        idempotency_key: str,
    ) -> CreatedWorkspaceInvitation: ...

    async def list_workspace_members(
        self, actor_id: UUID, workspace_id: UUID
    ) -> list[WorkspaceMemberView]: ...

    async def list_workspace_invitations(
        self, actor_id: UUID, workspace_id: UUID
    ) -> list[WorkspaceInvitationView]: ...

    async def accept_workspace_invitation(
        self, actor_id: UUID, token_hash: str
    ) -> WorkspaceMemberView | InvitationAcceptanceExpired: ...

    async def revoke_workspace_invitation(
        self,
        actor_id: UUID,
        workspace_id: UUID,
        invitation_id: UUID,
        idempotency_key: str,
    ) -> WorkspaceInvitationView: ...

    async def remove_workspace_member(
        self,
        actor_id: UUID,
        workspace_id: UUID,
        account_id: UUID,
        idempotency_key: str,
    ) -> None: ...

    async def list_project_members(
        self, actor_id: UUID, project_id: UUID
    ) -> list[ProjectMemberView]: ...

    async def set_project_member_role(
        self,
        actor_id: UUID,
        project_id: UUID,
        account_id: UUID,
        role: PermissionRole,
        idempotency_key: str,
    ) -> ProjectMemberView: ...

    async def remove_project_member(
        self,
        actor_id: UUID,
        project_id: UUID,
        account_id: UUID,
        idempotency_key: str,
    ) -> None: ...

    async def list_resource_permissions(
        self, actor_id: UUID, resource_id: UUID
    ) -> list[ResourcePermissionView]: ...

    async def set_resource_permission(
        self,
        actor_id: UUID,
        resource_id: UUID,
        account_id: UUID,
        role: PermissionRole,
        idempotency_key: str,
    ) -> ResourcePermissionView: ...

    async def remove_resource_permission(
        self,
        actor_id: UUID,
        resource_id: UUID,
        account_id: UUID,
        idempotency_key: str,
    ) -> None: ...
