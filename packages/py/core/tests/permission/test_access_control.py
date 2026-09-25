from __future__ import annotations

from app_core.permission.domain.access_control import (
    PermissionCapability,
    PermissionRole,
    effective_permission,
)


def test_archived_project_limits_all_roles_to_read() -> None:
    for role in PermissionRole:
        permission = effective_permission(role, project_read_only=True)

        assert permission.allows(PermissionCapability.READ)
        assert not permission.allows(PermissionCapability.EDIT)
        assert not permission.allows(PermissionCapability.COMMENT)
        assert not permission.allows(PermissionCapability.MANAGE)


def test_inactive_lifecycle_scopes_have_no_capabilities() -> None:
    denied = (
        effective_permission(PermissionRole.OWNER, workspace_active=False),
        effective_permission(PermissionRole.OWNER, project_active=False),
        effective_permission(PermissionRole.OWNER, resource_active=False),
    )

    assert all(permission.capabilities == frozenset() for permission in denied)
