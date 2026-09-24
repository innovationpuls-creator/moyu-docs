from __future__ import annotations

from typing import Protocol
from uuid import UUID

from app_core.history.domain import NamedVersion, VersionNode


class HistoryRepository(Protocol):
    """Merged read view: checkpoints (automatic/restore nodes) + named versions."""

    async def list_nodes(
        self, resource_id: UUID, *, limit: int = 100
    ) -> list[VersionNode]: ...
    async def create_named_version(
        self,
        resource_id: UUID,
        label: str,
        base_journal_seq: int,
        created_by: UUID | None,
    ) -> NamedVersion: ...
    async def named_label_exists(self, resource_id: UUID, label: str) -> bool: ...
