from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from app_core.permission.domain.access_control import PermissionRole


@dataclass(frozen=True)
class WorkspaceMemberView:
    workspace_id: UUID
    account_id: UUID
    email: str
    membership_kind: str
    created_at: datetime


@dataclass(frozen=True)
class WorkspaceInvitationView:
    invitation_id: UUID
    workspace_id: UUID
    target_email: str
    target_account_id: UUID | None
    role: str
    state: str
    expires_at: datetime
    created_by: UUID
    created_at: datetime
    accepted_at: datetime | None = None


@dataclass(frozen=True)
class CreatedWorkspaceInvitation:
    invitation: WorkspaceInvitationView
    invitation_url: str


@dataclass(frozen=True)
class WorkspaceInvitationNotice:
    invitation_id: UUID
    workspace_id: UUID
    workspace_name: str
    target_email: str
    target_account_id: UUID | None
    inviter_account_id: UUID
    inviter_email: str


@dataclass(frozen=True)
class InvitationAcceptanceExpired:
    """An expired invitation was recorded and can now be committed."""


@dataclass(frozen=True)
class ProjectMemberView:
    project_id: UUID
    account_id: UUID
    email: str
    role: PermissionRole
    membership_kind: str
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True)
class ResourcePermissionView:
    resource_id: UUID
    account_id: UUID
    email: str
    role: PermissionRole
    created_at: datetime
    updated_at: datetime
