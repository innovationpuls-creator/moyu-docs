from __future__ import annotations

from typing import Protocol
from uuid import UUID


class WorkspaceOwnershipQueryPort(Protocol):
    async def has_sole_workspace_ownership(
        self, account_id: UUID
    ) -> tuple[bool, str | None]: ...
