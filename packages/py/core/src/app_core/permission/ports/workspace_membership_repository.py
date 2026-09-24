from __future__ import annotations

from typing import Protocol
from uuid import UUID

from app_core.permission.domain.workspace_membership import (
    WorkspaceOwnerTransferResult,
)

SoleOwnedWorkspaceProjection = tuple[bool, str | None, UUID | None]


class AccountStatusProjection(Protocol):
    account_id: UUID
    status: str


class WorkspaceMembershipRepository(Protocol):
    async def grant_initial_owner(
        self, workspace_id: UUID, account_id: UUID
    ) -> None: ...

    async def transfer_owner_idempotently(
        self,
        actor_id: UUID,
        workspace_id: UUID,
        new_owner_id: UUID,
        idempotency_key: str,
    ) -> WorkspaceOwnerTransferResult: ...

    async def find_account(
        self, account_id: UUID
    ) -> AccountStatusProjection | None: ...

    async def has_sole_ownership(self, account_id: UUID) -> tuple[bool, str | None]: ...

    async def sole_owned_workspace(
        self, account_id: UUID
    ) -> SoleOwnedWorkspaceProjection: ...

    async def get_current_workspace_owner(self, workspace_id: UUID) -> UUID | None: ...
