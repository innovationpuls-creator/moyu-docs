from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from uuid import UUID

from app_core.common.exceptions import DomainError


class WorkspaceMembershipKind(StrEnum):
    OWNER = "Owner"
    MEMBER = "Member"


class WorkspaceOperation(StrEnum):
    CREATE = "Create"
    READ = "Read"
    MANAGE = "Manage"
    TRASH = "Trash"
    RESTORE = "Restore"
    PURGE = "Purge"


class PermissionDependencyError(DomainError):
    def __init__(self, message: str = "Permission dependency is unavailable.") -> None:
        super().__init__(message, "WORKSPACE_AUTHORIZATION_UNAVAILABLE", "Unavailable")


@dataclass(frozen=True)
class WorkspaceMembership:
    workspace_id: UUID
    account_id: UUID
    membership_kind: WorkspaceMembershipKind


@dataclass(frozen=True)
class WorkspaceOwnerTransferResult:
    workspace_id: UUID
    previous_owner_account_id: UUID
    new_owner_account_id: UUID
    transferred_at: datetime

    @property
    def previous_owner_remains_member(self) -> bool:
        return True

    @property
    def independent_project_owner_rows_changed(self) -> bool:
        return False


def can_manage_project(
    membership: WorkspaceMembership | None, project_workspace_id: UUID
) -> bool:
    return (
        membership is not None
        and membership.workspace_id == project_workspace_id
        and membership.membership_kind is WorkspaceMembershipKind.OWNER
    )
