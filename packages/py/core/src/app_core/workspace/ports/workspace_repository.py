from __future__ import annotations

from typing import TYPE_CHECKING, Protocol
from uuid import UUID

if TYPE_CHECKING:
    from app_core.workspace.application.use_cases import Workspace


class WorkspaceRepository(Protocol):
    """Workspace metadata persistence in the caller's transaction boundary."""

    async def save(self, workspace: Workspace) -> None: ...

    async def find_by_id(self, workspace_id: UUID) -> Workspace | None: ...
