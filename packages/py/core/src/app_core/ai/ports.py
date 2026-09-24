from __future__ import annotations

from datetime import datetime
from typing import Any, Protocol
from uuid import UUID

from app_core.ai.domain import ChangeSet


class AIChangeProvider(Protocol):
    """Adapter seam (arch 12): an AI returns proposed ops for a Resource."""

    async def propose(
        self,
        resource_id: UUID,
        instruction: str,
        *,
        snapshot: dict[str, Any] | None,
    ) -> list[dict[str, Any]]: ...


class ChangeSetRepository(Protocol):
    async def save(self, changeset: ChangeSet) -> ChangeSet: ...
    async def find_by_id(self, changeset_id: UUID) -> ChangeSet | None: ...
    async def mark_applied(
        self, changeset_id: UUID, *, applied_at: datetime
    ) -> None: ...
