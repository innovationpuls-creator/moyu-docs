from __future__ import annotations

import hashlib
import secrets
from datetime import UTC, datetime, timedelta
from urllib.parse import quote
from uuid import UUID

from app_core.common.exceptions import NotFoundError, ValidationError
from app_core.permission.domain.access_control import (
    EffectivePermission,
    PermissionCapability,
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
from app_core.permission.ports.permission_administration import (
    PermissionAdministrationRepository,
)


class PermissionAdministration:
    def __init__(
        self,
        repository: PermissionAdministrationRepository,
        *,
        now=lambda: datetime.now(UTC),
        token_factory=secrets.token_urlsafe,
    ) -> None:
        self._repository = repository
        self._now = now
        self._token_factory = token_factory

    async def get_resource_capabilities(
        self, actor_id: UUID, resource_id: UUID
    ) -> EffectivePermission:
        permission = await self._repository.get_resource_capabilities(
            actor_id, resource_id
        )
        if permission is None or not permission.allows(PermissionCapability.READ):
            raise NotFoundError("Resource not found.", "RESOURCE_NOT_FOUND")
        return permission

    async def create_workspace_invitation(
        self,
        actor_id: UUID,
        workspace_id: UUID,
        target_email: str,
        idempotency_key: str,
        expires_in_days: int = 7,
    ) -> CreatedWorkspaceInvitation:
        if not 1 <= expires_in_days <= 30:
            raise ValidationError(
                "Invitation expiry must be between 1 and 30 days.",
                "INVITATION_EXPIRY_INVALID",
                "expiresInDays",
            )
        email = target_email.strip().casefold()
        if not email or "@" not in email:
            raise ValidationError(
                "A valid target email is required.",
                "INVITATION_EMAIL_INVALID",
                "targetEmail",
            )
        token = self._token_factory(32)
        token_hash = hashlib.sha256(token.encode()).hexdigest()
        expires_at = self._now() + timedelta(days=expires_in_days)
        invitation_url = f"/invite/accept?token={quote(token, safe='')}"
        return await self._repository.create_workspace_invitation(
            actor_id,
            workspace_id,
            email,
            token_hash,
            invitation_url,
            expires_at,
            expires_in_days,
            idempotency_key,
        )

    async def list_workspace_members(
        self, actor_id: UUID, workspace_id: UUID
    ) -> list[WorkspaceMemberView]:
        return await self._repository.list_workspace_members(actor_id, workspace_id)

    async def list_workspace_invitations(
        self, actor_id: UUID, workspace_id: UUID
    ) -> list[WorkspaceInvitationView]:
        return await self._repository.list_workspace_invitations(actor_id, workspace_id)

    async def accept_workspace_invitation(
        self, actor_id: UUID, token: str
    ) -> WorkspaceMemberView | InvitationAcceptanceExpired:
        if not token:
            raise ValidationError(
                "Invitation token is required.", "INVITATION_INVALID", "token"
            )
        token_hash = hashlib.sha256(token.encode()).hexdigest()
        return await self._repository.accept_workspace_invitation(actor_id, token_hash)

    async def revoke_workspace_invitation(
        self,
        actor_id: UUID,
        workspace_id: UUID,
        invitation_id: UUID,
        idempotency_key: str,
    ) -> WorkspaceInvitationView:
        return await self._repository.revoke_workspace_invitation(
            actor_id, workspace_id, invitation_id, idempotency_key
        )

    async def remove_workspace_member(
        self,
        actor_id: UUID,
        workspace_id: UUID,
        account_id: UUID,
        idempotency_key: str,
    ) -> None:
        await self._repository.remove_workspace_member(
            actor_id, workspace_id, account_id, idempotency_key
        )

    async def list_project_members(
        self, actor_id: UUID, project_id: UUID
    ) -> list[ProjectMemberView]:
        return await self._repository.list_project_members(actor_id, project_id)

    async def set_project_member_role(
        self,
        actor_id: UUID,
        project_id: UUID,
        account_id: UUID,
        role: PermissionRole,
        idempotency_key: str,
    ) -> ProjectMemberView:
        return await self._repository.set_project_member_role(
            actor_id, project_id, account_id, role, idempotency_key
        )

    async def remove_project_member(
        self,
        actor_id: UUID,
        project_id: UUID,
        account_id: UUID,
        idempotency_key: str,
    ) -> None:
        await self._repository.remove_project_member(
            actor_id, project_id, account_id, idempotency_key
        )

    async def list_resource_permissions(
        self, actor_id: UUID, resource_id: UUID
    ) -> list[ResourcePermissionView]:
        return await self._repository.list_resource_permissions(actor_id, resource_id)

    async def set_resource_permission(
        self,
        actor_id: UUID,
        resource_id: UUID,
        account_id: UUID,
        role: PermissionRole,
        idempotency_key: str,
    ) -> ResourcePermissionView:
        return await self._repository.set_resource_permission(
            actor_id, resource_id, account_id, role, idempotency_key
        )

    async def remove_resource_permission(
        self,
        actor_id: UUID,
        resource_id: UUID,
        account_id: UUID,
        idempotency_key: str,
    ) -> None:
        await self._repository.remove_resource_permission(
            actor_id, resource_id, account_id, idempotency_key
        )
