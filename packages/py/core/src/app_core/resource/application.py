from __future__ import annotations

import hashlib
import json
from collections.abc import Awaitable
from typing import Callable
from uuid import UUID, uuid4

from app_core.resource.domain import (
    Checkpoint,
    JournalOp,
    JournalSequenceConflictError,
    Resource,
    ResourceLifecycle,
    ResourceNameConflictError,
    ResourceNotFoundError,
    ResourcePermissionDeniedError,
    normalize_resource_name,
)
from app_core.resource.ports import (
    CheckpointRepository,
    JournalIdempotencyPort,
    JournalRepository,
    ReadOnlyResourceOwnershipPort,
    ResourceEventPublisher,
    ResourceRepository,
)


class CreateResource:
    def __init__(
        self,
        resources: ResourceRepository,
        ownership: ReadOnlyResourceOwnershipPort,
        events: ResourceEventPublisher | None = None,
    ) -> None:
        self._resources = resources
        self._ownership = ownership
        self._events = events

    async def execute(
        self,
        actor_id: UUID,
        *,
        project_id: UUID,
        resource_type: str,
        name: str,
        folder_id: UUID | None = None,
        resource_id: UUID | None = None,
    ) -> Resource:
        if not await self._ownership.authorize(actor_id, project_id, "resource.create"):
            raise ResourcePermissionDeniedError("no resource.create permission")
        if folder_id is not None:
            folder_matches = await self._resources.folder_belongs_to_project(
                folder_id, project_id
            )
            if not folder_matches:
                raise ResourceNotFoundError("folder is not in the project")
        normalized = normalize_resource_name(name)
        if await self._resources.sibling_exists(project_id, normalized):
            raise ResourceNameConflictError(name)
        resource = Resource(
            resource_id=resource_id or uuid4(),
            project_id=project_id,
            folder_id=folder_id,
            resource_type=resource_type,
            name=name,
            normalized_name=normalized,
            lifecycle=ResourceLifecycle.ACTIVE,
        )
        saved = await self._resources.create(resource)
        if self._events is not None:
            await self._events.publish(
                "resource.created.v1",
                saved.resource_id,
                {
                    "resourceId": str(saved.resource_id),
                    "resourceType": saved.resource_type,
                },
            )
        return saved


class AppendJournalOp:
    def __init__(
        self,
        resources: ResourceRepository,
        journal: JournalRepository,
        ownership: ReadOnlyResourceOwnershipPort,
        events: ResourceEventPublisher | None = None,
        idempotency: JournalIdempotencyPort | None = None,
    ) -> None:
        self._resources = resources
        self._journal = journal
        self._ownership = ownership
        self._events = events
        self._idempotency = idempotency

    async def execute(
        self,
        actor_id: UUID,
        resource_id: UUID,
        update_bytes: bytes,
        *,
        ownership_epoch: int,
        expected_seq: int | None = None,
        idempotency_key: str | None = None,
    ) -> JournalOp:
        if not await self._ownership.authorize(
            actor_id, resource_id, "resource.update"
        ):
            raise ResourcePermissionDeniedError("no resource.update permission")
        current = await self._resources.get(resource_id)
        if current is None:
            raise LookupError("resource not found")
        update_hash = JournalOp.hash_of(update_bytes)

        async def append() -> JournalOp:
            seq = (await self._journal.max_seq(resource_id)) + 1
            if expected_seq is not None and expected_seq != seq:
                raise JournalSequenceConflictError(seq)
            return await self._journal.append_op(
                resource_id,
                seq,
                ownership_epoch,
                update_bytes,
                update_hash,
                expected_seq=expected_seq,
            )

        if idempotency_key and self._idempotency is not None:
            fingerprint = hashlib.sha256(
                json.dumps(
                    {
                        "actorId": str(actor_id),
                        "resourceId": str(resource_id),
                        "expectedSeq": expected_seq,
                        "ownershipEpoch": ownership_epoch,
                        "updateSha256": update_hash,
                    },
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode()
            ).hexdigest()
            saved = await self._idempotency.execute(
                f"{actor_id}:{resource_id}:{idempotency_key}", fingerprint, append
            )
        else:
            saved = await append()
        if self._events is not None:
            await self._events.publish(
                "resource.journal-appended.v1",
                resource_id,
                {"resourceId": str(resource_id), "journalSeq": saved.journal_seq},
            )
        return saved


class RenameResource:
    """FR-RC-004: rename an authorized Resource (sibling reservation kept)."""

    def __init__(
        self,
        resources: ResourceRepository,
        ownership: ReadOnlyResourceOwnershipPort,
    ) -> None:
        self._resources = resources
        self._ownership = ownership

    async def execute(
        self,
        actor_id: UUID,
        resource_id: UUID,
        *,
        name: str,
    ) -> Resource:
        if not await self._ownership.authorize(
            actor_id, resource_id, "resource.update"
        ):
            raise ResourcePermissionDeniedError("no resource.update permission")
        current = await self._resources.get(resource_id)
        if current is None:
            raise LookupError("resource not found")
        normalized = normalize_resource_name(name)
        if (
            current.normalized_name != normalized
            and await self._resources.sibling_exists(current.project_id, normalized)
        ):
            raise ResourceNameConflictError(name)
        saved = await self._resources.rename(resource_id, name, normalized)
        return saved


class TrashResource:
    """FR-RC-005: move an authorized Resource to Trashed (name stays reserved)."""

    def __init__(
        self,
        resources: ResourceRepository,
        ownership: ReadOnlyResourceOwnershipPort,
    ) -> None:
        self._resources = resources
        self._ownership = ownership

    async def execute(
        self,
        actor_id: UUID,
        resource_id: UUID,
    ) -> Resource:
        if not await self._ownership.authorize(
            actor_id, resource_id, "resource.manage"
        ):
            raise ResourcePermissionDeniedError("no resource.manage permission")
        current = await self._resources.get(resource_id)
        if current is None:
            raise LookupError("resource not found")
        if current.lifecycle not in (ResourceLifecycle.ACTIVE,):
            # Trash is only meaningful from Active; otherwise no-op with the
            # current state (idempotent surface for retries).
            return current
        saved = await self._resources.set_lifecycle(resource_id, "Trashed")
        assert saved is not None
        return saved


class RestoreResource:
    """FR-RC-005: restore a Trashed Resource back to Active."""

    def __init__(
        self,
        resources: ResourceRepository,
        ownership: ReadOnlyResourceOwnershipPort,
    ) -> None:
        self._resources = resources
        self._ownership = ownership

    async def execute(
        self,
        actor_id: UUID,
        resource_id: UUID,
    ) -> Resource:
        if not await self._ownership.authorize(
            actor_id, resource_id, "resource.restore"
        ):
            raise ResourcePermissionDeniedError("no resource.restore permission")
        current = await self._resources.get(resource_id)
        if current is None:
            raise LookupError("resource not found")
        if current.lifecycle != ResourceLifecycle.TRASHED:
            # Restore is only meaningful from Trashed; otherwise surface the
            # current state (idempotent for retries).
            return current
        saved = await self._resources.set_lifecycle(resource_id, "Active")
        assert saved is not None
        return saved


class ExportResource:
    """FR-IE-001: build the versioned exchange document from metadata + the
    latest checkpoint snapshot (requires read access)."""

    def __init__(
        self,
        resources: ResourceRepository,
        checkpoints: CheckpointRepository,
        ownership: ReadOnlyResourceOwnershipPort,
    ) -> None:
        self._resources = resources
        self._checkpoints = checkpoints
        self._ownership = ownership

    async def execute(self, actor_id: UUID, resource_id: UUID) -> dict:
        if not await self._ownership.authorize(actor_id, resource_id, "resource.read"):
            raise ResourcePermissionDeniedError("no resource.read permission")
        current = await self._resources.get(resource_id)
        if current is None:
            raise LookupError("resource not found")
        latest = await self._checkpoints.latest(resource_id)
        return {
            "kind": "dom.resource.export.v1",
            "schemaVersion": "1.0.0",
            "resource": {
                "resourceId": str(current.resource_id),
                "resourceType": current.resource_type,
                "name": current.name,
            },
            "content": {
                "snapshot": latest.snapshot if latest is not None else None,
                "journalSeq": latest.base_journal_seq if latest is not None else 0,
            },
        }


class ImportResource:
    """FR-IE-002: import a snapshot INTO the resource as a new checkpoint;
    the import itself is recorded as a journal op (update = the document)."""

    def __init__(
        self,
        resources: ResourceRepository,
        journal: JournalRepository,
        checkpoints: CheckpointRepository,
        ownership: ReadOnlyResourceOwnershipPort,
    ) -> None:
        self._resources = resources
        self._journal = journal
        self._checkpoints = checkpoints
        self._ownership = ownership

    async def execute(
        self,
        actor_id: UUID,
        resource_id: UUID,
        document: dict,
    ) -> tuple[int, Checkpoint]:
        if document.get("kind") != "dom.resource.export.v1":
            raise ValueError("IMPORT_DOCUMENT_INVALID")
        if not await self._ownership.authorize(
            actor_id, resource_id, "resource.update"
        ):
            raise ResourcePermissionDeniedError("no resource.update permission")
        current = await self._resources.get(resource_id)
        if current is None:
            raise LookupError("resource not found")
        payload = __import__("json").dumps(document, default=str).encode()
        seq = (await self._journal.max_seq(resource_id)) + 1
        await self._journal.append_op(
            resource_id,
            seq,
            1,
            payload,
            __import__("hashlib").sha256(payload).hexdigest(),
        )
        snapshot = (document.get("content") or {}).get("snapshot")
        checkpoint = await self._checkpoints.write(
            resource_id, seq, snapshot if snapshot is not None else {"imported": True}
        )
        return seq, checkpoint


class ReadJournal:
    def __init__(self, journal: JournalRepository) -> None:
        self._journal = journal

    async def execute(
        self, resource_id: UUID, after_seq: int, *, limit: int = 200
    ) -> list[JournalOp]:
        return await self._journal.read_cursor(resource_id, after_seq, limit=limit)


class ReadCurrentResourceContent:
    """Read the durable projection and journal boundary for a Resource."""

    def __init__(
        self,
        resources: ResourceRepository,
        journal: JournalRepository,
        checkpoints: CheckpointRepository,
        ownership: ReadOnlyResourceOwnershipPort,
    ) -> None:
        self._resources = resources
        self._journal = journal
        self._checkpoints = checkpoints
        self._ownership = ownership

    async def execute(self, actor_id: UUID, resource_id: UUID) -> dict:
        if not await self._ownership.authorize(actor_id, resource_id, "resource.read"):
            raise ResourcePermissionDeniedError("no resource.read permission")
        resource = await self._resources.get(resource_id)
        if resource is None or resource.lifecycle != ResourceLifecycle.ACTIVE:
            raise LookupError("resource not found")
        checkpoint = await self._checkpoints.latest(resource_id)
        return {
            "resourceId": str(resource.resource_id),
            "name": resource.name,
            "resourceType": resource.resource_type,
            "snapshot": checkpoint.snapshot if checkpoint is not None else None,
            "checkpointJournalSeq": (
                checkpoint.base_journal_seq if checkpoint is not None else 0
            ),
            "journalSeq": await self._journal.max_seq(resource_id),
        }


class CheckpointResource:
    def __init__(
        self,
        journal: JournalRepository,
        checkpoints: CheckpointRepository,
        events: ResourceEventPublisher | None = None,
    ) -> None:
        self._journal = journal
        self._checkpoints = checkpoints
        self._events = events

    async def execute(
        self,
        resource_id: UUID,
        snapshot: dict,
        *,
        created_by: UUID | None = None,
        truncate_after: bool = False,
    ) -> Checkpoint:
        base = await self._journal.max_seq(resource_id)
        saved = await self._checkpoints.write(
            resource_id, base, snapshot, created_by=created_by
        )
        if truncate_after and base > 0:
            await self._checkpoints.truncate_before(resource_id, base)
        if self._events is not None:
            await self._events.publish(
                "resource.checkpointed.v1",
                resource_id,
                {
                    "resourceId": str(resource_id),
                    "checkpointSeq": saved.checkpoint_seq,
                    "baseJournalSeq": saved.base_journal_seq,
                },
            )
        return saved


class RestoreAtRevision:
    def __init__(
        self,
        journal: JournalRepository,
        checkpoints: CheckpointRepository,
        apply: Callable[[dict, JournalOp], dict],
    ) -> None:
        self._journal = journal
        self._checkpoints = checkpoints
        self._apply = apply

    async def execute(
        self,
        resource_id: UUID,
        target_seq: int,
        *,
        on_progress: Callable[[int, int], Awaitable[None]] | None = None,
    ) -> dict:
        latest = await self._checkpoints.latest(resource_id)
        base_seq = 0
        state: dict = {}
        if latest is not None and latest.base_journal_seq <= target_seq:
            state = dict(latest.snapshot)
            base_seq = latest.base_journal_seq
        ops = await self._journal.read_cursor(
            resource_id, base_seq, limit=target_seq - base_seq + 1
        )
        replay_ops = [op for op in ops if op.journal_seq <= target_seq]
        total = len(replay_ops)
        if on_progress is not None:
            await on_progress(0, total)
        for current, op in enumerate(replay_ops, start=1):
            state = self._apply(state, op)
            if on_progress is not None and (current % 100 == 0 or current == total):
                await on_progress(current, total)
        return state
