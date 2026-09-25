from __future__ import annotations

from collections.abc import Awaitable
from typing import Any, Callable
from uuid import UUID

from app_core.history.domain import (
    NamedVersion,
    NamedVersionLabelConflictError,
    VersionKind,
    VersionNode,
)
from app_core.history.ports import HistoryRepository
from app_core.resource.application import RestoreAtRevision
from app_core.resource.ports import (
    CheckpointRepository,
    JournalRepository,
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
    """Arch 08 §17-19: restore = a NEW current modification, never a rewind.

    Materializes the historical state (RestoreAtRevision), appends a RESTORE
    marker journal op, and writes a NEW checkpoint whose snapshot is the
    restored state. The previous current remains reachable.
    """

    def __init__(
        self,
        history: HistoryRepository,
        resources: ResourceRepository,
        journal: JournalRepository,
        checkpoints: CheckpointRepository,
        apply: Callable[[dict, Any], dict],
    ) -> None:
        self._history = history
        self._resources = resources
        self._journal = journal
        self._checkpoints = checkpoints
        self._apply = apply

    async def execute(
        self,
        resource_id: UUID,
        target_seq: int,
        *,
        actor_id: UUID | None = None,
        on_progress: Callable[[str, int | None, int | None], Awaitable[None]]
        | None = None,
    ) -> VersionNode:
        current = await self._resources.get(resource_id)
        if current is None:
            raise LookupError("resource not found")
        restore = RestoreAtRevision(self._journal, self._checkpoints, self._apply)
        if on_progress is not None:
            await on_progress("materializing", None, None)

        async def report_replay(current_count: int, total_count: int) -> None:
            if on_progress is not None:
                await on_progress("replaying", current_count, total_count)

        restored_state = await restore.execute(
            resource_id,
            target_seq,
            on_progress=report_replay if on_progress is not None else None,
        )
        if on_progress is not None:
            await on_progress("saving", None, None)
        base_seq = await self._journal.max_seq(resource_id)
        next_seq = base_seq + 1
        marker = f"restore@v{target_seq}".encode()
        await self._journal.append_op(
            resource_id,
            next_seq,
            1,  # ownership epoch of the restore marker op
            marker,
            __import__("hashlib").sha256(marker).hexdigest(),
        )
        checkpoint = await self._checkpoints.write(
            resource_id, next_seq, restored_state, created_by=actor_id
        )
        return VersionNode(
            node_id=checkpoint.resource_id,
            resource_id=resource_id,
            kind=VersionKind.RESTORE,
            label=f"restore to v{target_seq}",
            author=actor_id,
            occurred_at=checkpoint.created_at,
            base_journal_seq=next_seq,
            op_count=1,
            summary=f"restored from revision {target_seq}",
        )
