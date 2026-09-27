from __future__ import annotations

from collections.abc import Awaitable
from datetime import UTC, datetime
from typing import Callable
from uuid import UUID, uuid4

from app_core.history.domain import (
    NamedVersion,
    NamedVersionLabelConflictError,
    VersionKind,
    VersionNode,
)
from app_core.history.ports import HistoryRepository
from app_core.resource.ports import (
    ResourceContentPort,
    ResourceRepository,
)


class ListVersions:
    def __init__(self, history: HistoryRepository) -> None:
        self._history = history

    async def execute(
        self, resource_id: UUID, *, limit: int = 100
    ) -> list[VersionNode]:
        return await self._history.list_nodes(resource_id, limit=limit)


class CreateNamedVersion:
    def __init__(self, history: HistoryRepository) -> None:
        self._history = history

    async def execute(
        self,
        resource_id: UUID,
        label: str,
        *,
        base_journal_seq: int,
        created_by: UUID | None = None,
    ) -> NamedVersion:
        if not label.strip():
            raise NamedVersionLabelConflictError(
                "named version label must not be empty"
            )
        if await self._history.named_label_exists(resource_id, label):
            raise NamedVersionLabelConflictError(label)
        return await self._history.create_named_version(
            resource_id, label, base_journal_seq, created_by
        )


class RestoreAtVersion:
    """Restore a historical semantic state as a new durable Yjs mutation."""

    def __init__(
        self,
        resources: ResourceRepository,
        content: ResourceContentPort,
    ) -> None:
        self._resources = resources
        self._content = content

    async def execute(
        self,
        resource_id: UUID,
        target_seq: int,
        *,
        actor_id: UUID | None = None,
        operation_id: UUID | None = None,
        on_progress: Callable[[str, int | None, int | None], Awaitable[None]]
        | None = None,
    ) -> VersionNode:
        current = await self._resources.get(resource_id)
        if current is None:
            raise LookupError("resource not found")
        if on_progress is not None:
            await on_progress("materializing", None, None)
        restored_content = await self._content.read(
            resource_id, at_journal_seq=target_seq
        )
        if restored_content.journal_seq != target_seq:
            raise LookupError("history restore version no longer exists")
        if on_progress is not None:
            await on_progress("saving", None, None)
        receipt = await self._content.replace(
            resource_id,
            restored_content.snapshot,
            operation_id=operation_id or uuid4(),
            created_by=actor_id,
            reason="history-restore",
            restore_target_seq=target_seq,
        )
        now = datetime.now(UTC)
        return VersionNode(
            node_id=uuid4(),
            resource_id=resource_id,
            kind=VersionKind.RESTORE,
            label=f"restore to v{target_seq}",
            author=actor_id,
            occurred_at=now,
            base_journal_seq=receipt.journal_seq,
            op_count=1,
            summary=f"restored from revision {target_seq}",
        )
