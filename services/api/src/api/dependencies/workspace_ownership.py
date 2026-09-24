"""Permission-owned Workspace ownership query adapters."""

from __future__ import annotations

from uuid import UUID

from app_core.account.ports.workspace_ownership_query_port import (
    WorkspaceOwnershipQueryPort,
)
from app_core.permission.ports.workspace_membership_repository import (
    SoleOwnedWorkspaceProjection,
)
from app_infra.postgres.permission_workspace_repository import (
    PostgresWorkspaceMembershipRepository,
)
from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from api.dependencies.auth import get_db_session

__all__ = [
    "PostgresWorkspaceOwnershipQuery",
    "WorkspaceOwnershipQueryPort",
    "get_workspace_ownership",
]


class PostgresWorkspaceOwnershipQuery(WorkspaceOwnershipQueryPort):
    """Bridge Permission's authoritative ownership projection to Auth."""

    def __init__(self, session: AsyncSession) -> None:
        self._membership_repository = PostgresWorkspaceMembershipRepository(session)

    async def sole_owned_workspace(
        self, account_id: UUID
    ) -> SoleOwnedWorkspaceProjection:
        return await self._membership_repository.sole_owned_workspace(account_id)

    async def has_sole_workspace_ownership(
        self, account_id: UUID
    ) -> tuple[bool, str | None]:
        is_sole, workspace_name, _ = await self.sole_owned_workspace(account_id)
        return is_sole, workspace_name


async def get_workspace_ownership(
    session: AsyncSession = Depends(get_db_session),
) -> PostgresWorkspaceOwnershipQuery:
    return PostgresWorkspaceOwnershipQuery(session)
