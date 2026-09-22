"""Workspace-ownership adapter seam (plan Task 12 / Task 24).

The RequestAccountDeletion use case consults ``WorkspaceOwnershipQueryPort`` to
block deleting an account that is the sole owner of a non-deleted workspace
(FR-AUTH-029 / doc 16 §41). The Workspace module is a FUTURE feature and must
not be prematurely coupled to this API (doc 27 §16): Phase 7 wires a no-owner
adapter that always reports "no sole ownership", so the deletion flow operates
with the workspace barrier disabled until the Workspace domain lands.

Seam contract:
- The PROTOCOL is ``app_core.account.ports.workspace_ownership_query_port``
  (single source; the application use case imports it).
- The IMPLEMENTATION here is the Phase 7 placeholder; the future Workspace
  feature provides the real ownership query and replaces this adapter via the
  same ``get_workspace_ownership`` dependency injection point (tests override
  it with sole-owner adapters).
"""

from __future__ import annotations

from uuid import UUID

from app_core.account.ports.workspace_ownership_query_port import (
    WorkspaceOwnershipQueryPort,
)

__all__ = [
    "NoOwnedWorkspacesQuery",
    "WorkspaceOwnershipQueryPort",
    "get_workspace_ownership",
]


class NoOwnedWorkspacesQuery(WorkspaceOwnershipQueryPort):
    """Phase 7 placeholder: no account is the sole owner of any workspace.

    TODO(workspaces): replace with the real Workspace ownership query when the
    Workspace module lands (doc 16 §41, FR-AUTH-029). Deleting an account is
    currently NEVER blocked on workspace-ownership grounds.
    """

    async def has_sole_workspace_ownership(
        self, account_id: UUID
    ) -> tuple[bool, str | None]:
        return False, None


def get_workspace_ownership() -> WorkspaceOwnershipQueryPort:
    return NoOwnedWorkspacesQuery()
