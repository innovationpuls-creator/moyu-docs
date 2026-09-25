from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class PermissionRole(StrEnum):
    OWNER = "Owner"
    MANAGE = "Manage"
    EDIT = "Edit"
    COMMENT = "Comment"
    READ = "Read"


class PermissionCapability(StrEnum):
    READ = "resource.read"
    EDIT = "resource.update"
    COMMENT = "resource.comment"
    RESOLVE_COMMENT = "comment.resolve"
    REOPEN_COMMENT = "comment.reopen"
    MANAGE = "resource.manage"
    PURGE = "resource.purge"
    MANAGE_MEMBERS = "permission.manage_members"
    TRANSFER_OWNER = "permission.transfer_owner"


@dataclass(frozen=True)
class EffectivePermission:
    role: PermissionRole | None
    capabilities: frozenset[PermissionCapability]

    def allows(self, capability: PermissionCapability) -> bool:
        return capability in self.capabilities


_CAPABILITIES_BY_ROLE = {
    PermissionRole.OWNER: frozenset(PermissionCapability),
    PermissionRole.MANAGE: frozenset(
        {
            PermissionCapability.READ,
            PermissionCapability.EDIT,
            PermissionCapability.COMMENT,
            PermissionCapability.RESOLVE_COMMENT,
            PermissionCapability.REOPEN_COMMENT,
            PermissionCapability.MANAGE,
            PermissionCapability.MANAGE_MEMBERS,
        }
    ),
    PermissionRole.EDIT: frozenset(
        {
            PermissionCapability.READ,
            PermissionCapability.EDIT,
            PermissionCapability.COMMENT,
            PermissionCapability.RESOLVE_COMMENT,
            PermissionCapability.REOPEN_COMMENT,
        }
    ),
    PermissionRole.COMMENT: frozenset(
        {PermissionCapability.READ, PermissionCapability.COMMENT}
    ),
    PermissionRole.READ: frozenset({PermissionCapability.READ}),
}


def effective_permission(
    project_role: PermissionRole | None,
    resource_override: PermissionRole | None = None,
    *,
    workspace_owner: bool = False,
    workspace_active: bool = True,
    project_active: bool = True,
    project_read_only: bool = False,
    resource_active: bool = True,
) -> EffectivePermission:
    """Resolve direct Resource overrides separately from Workspace membership.

    Workspace Owner's documented Project Manage inheritance is evaluated at
    request time and is never persisted as a project membership row.
    """
    role: PermissionRole | None
    if project_role is PermissionRole.OWNER:
        role = PermissionRole.OWNER
    elif workspace_owner:
        role = PermissionRole.MANAGE
    else:
        role = resource_override if resource_override is not None else project_role
    capabilities = _CAPABILITIES_BY_ROLE[role] if role is not None else frozenset()
    if not workspace_active or not project_active or not resource_active:
        capabilities = frozenset()
    elif project_read_only:
        capabilities &= frozenset({PermissionCapability.READ})
    return EffectivePermission(role=role, capabilities=capabilities)
