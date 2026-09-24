from __future__ import annotations

from typing import Protocol
from uuid import UUID

from app_core.resource.domain import (
    Checkpoint,
    JournalOp,
    Resource,
)


class ResourceRepository(Protocol):
    async def create(self, resource: Resource) -> Resource: ...
    async def get(self, resource_id: UUID) -> Resource | None: ...
    async def rename(
        self, resource_id: UUID, name: str, normalized_name: str
    ) -> Resource: ...
    async def set_lifecycle(
        self, resource_id: UUID, lifecycle: str
    ) -> Resource | None: ...
    async def sibling_exists(self, project_id: UUID, normalized_name: str) -> bool: ...


class JournalRepository(Protocol):
    async def append_op(
        self,
        resource_id: UUID,
        journal_seq: int,
        ownership_epoch: int,
        update_bytes: bytes,
        update_hash: str,
    ) -> JournalOp: ...
    async def read_cursor(
        self, resource_id: UUID, after_seq: int, *, limit: int = 200
    ) -> list[JournalOp]: ...
    async def max_seq(self, resource_id: UUID) -> int: ...
    async def mark_durable(self, resource_id: UUID, journal_seq: int) -> None: ...


class CheckpointRepository(Protocol):
    async def write(
        self,
        resource_id: UUID,
        base_journal_seq: int,
        snapshot: dict,
        created_by: UUID | None = None,
    ) -> Checkpoint: ...
    async def latest(self, resource_id: UUID) -> Checkpoint | None: ...
    async def truncate_before(self, resource_id: UUID, journal_seq: int) -> int: ...
    async def list_recent(
        self, resource_id: UUID, *, limit: int = 10
    ) -> list[Checkpoint]: ...


class ReadOnlyResourceOwnershipPort(Protocol):
    """Permission-owned authorization check; Resource never writes ownership."""

    async def authorize(
        self, actor_id: UUID, scope_id: UUID, operation: str
    ) -> bool: ...


class ResourceEventPublisher(Protocol):
    async def publish(
        self, event_type: str, resource_id: UUID, payload: dict
    ) -> None: ...
