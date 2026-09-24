from __future__ import annotations

from typing import Protocol
from uuid import UUID

from app_core.permission.domain.workspace_membership import WorkspaceOperation


class WorkspaceAccessPort(Protocol):
    """Permission decisions for ordinary access checks.

    Owner transfer is excluded: its repository operation serializes the
    authoritative Owner check with membership validation and mutation.
    """

    async def authorize(
        self,
        actor_id: UUID,
        operation: WorkspaceOperation,
        *,
        workspace_id: UUID,
        project_id: UUID | None = None,
    ) -> None: ...
