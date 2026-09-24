from __future__ import annotations

from typing import Protocol
from uuid import UUID

from app_core.account.domain.account import AccountStatus


class AccountWorkspaceEligibilityPort(Protocol):
    """Read Account-owned status used to gate Workspace creation."""

    async def workspace_creation_status(
        self, actor_id: UUID
    ) -> AccountStatus | None: ...
