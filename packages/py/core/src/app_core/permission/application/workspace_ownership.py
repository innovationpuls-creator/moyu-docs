from __future__ import annotations

from uuid import UUID

from app_core.permission.domain.workspace_membership import (
    WorkspaceOwnerTransferResult,
)
from app_core.permission.ports.workspace_membership_repository import (
    WorkspaceMembershipRepository,
)


class GrantInitialWorkspaceOwner:
    def __init__(self, memberships: WorkspaceMembershipRepository) -> None:
        self.memberships = memberships

    async def execute(self, workspace_id: UUID, actor_id: UUID) -> None:
        await self.memberships.grant_initial_owner(workspace_id, actor_id)


class TransferWorkspaceOwner:
    def __init__(self, memberships: WorkspaceMembershipRepository) -> None:
        self.memberships = memberships

    async def execute(
        self,
        actor_id: UUID,
        workspace_id: UUID,
        new_owner_id: UUID,
        idempotency_key: str,
    ) -> WorkspaceOwnerTransferResult:
        return await self.memberships.transfer_owner_idempotently(
            actor_id,
            workspace_id,
            new_owner_id,
            idempotency_key,
        )


class GetCurrentWorkspaceOwner:
    def __init__(self, memberships: WorkspaceMembershipRepository) -> None:
        self.memberships = memberships

    async def execute(self, workspace_id: UUID) -> UUID | None:
        return await self.memberships.get_current_workspace_owner(workspace_id)


class HasSoleWorkspaceOwnership:
    def __init__(self, memberships: WorkspaceMembershipRepository) -> None:
        self.memberships = memberships

    async def execute(self, account_id: UUID) -> tuple[bool, str | None]:
        return await self.memberships.has_sole_ownership(account_id)
