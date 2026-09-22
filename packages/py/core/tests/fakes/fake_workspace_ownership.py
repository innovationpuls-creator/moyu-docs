from __future__ import annotations

from uuid import UUID

from app_core.account.ports.workspace_ownership_query_port import (
    WorkspaceOwnershipQueryPort,
)


class FakeWorkspaceOwnershipQueryAdapter(WorkspaceOwnershipQueryPort):
    """In-memory WorkspaceOwnershipQueryPort fake.

    Defaults to no sole ownership; call set_sole_ownership to mark an account
    as the sole owner of a named workspace (plan Task 12).
    """

    def __init__(self) -> None:
        self._sole_owner_workspaces: dict[UUID, str] = {}

    def set_sole_ownership(self, account_id: UUID, workspace_name: str) -> None:
        self._sole_owner_workspaces[account_id] = workspace_name

    async def has_sole_workspace_ownership(
        self, account_id: UUID
    ) -> tuple[bool, str | None]:
        if account_id in self._sole_owner_workspaces:
            return True, self._sole_owner_workspaces[account_id]
        return False, None
