from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from app_core.ai.domain import ChangeSet, ChangesetError, ChangesetStatus
from app_core.ai.ports import AIChangeProvider, ChangeSetRepository
from app_core.resource.ports import ReadOnlyResourceOwnershipPort


class ProposeChangeSet:
    """Arch 12 §6: AI output never writes directly — it becomes a ChangeSet."""

    def __init__(
        self,
        changesets: ChangeSetRepository,
        resources: Any,
        provider: AIChangeProvider,
        ownership: ReadOnlyResourceOwnershipPort,
    ) -> None:
        self._changesets = changesets
        self._resources = resources
        self._provider = provider
        self._ownership = ownership

    async def execute(
        self,
        actor_id: UUID,
        resource_id: UUID,
        *,
        instruction: str,
    ) -> ChangeSet:
        if not await self._ownership.authorize(actor_id, resource_id, "resource.read"):
            raise ChangesetError("no resource.read permission")
        current = await self._resources.get(resource_id)
        if current is None:
            raise LookupError("resource not found")
        from app_core.resource.ports import CheckpointRepository

        snapshots: CheckpointRepository | None = None
        snapshot = None
        if snapshots is not None:
            latest = await snapshots.latest(resource_id)
            snapshot = latest.snapshot if latest is not None else None
        ops = await self._provider.propose(resource_id, instruction, snapshot=snapshot)
        changeset = ChangeSet(
            changeset_id=uuid4(),
            resource_id=resource_id,
            instruction=instruction,
            ops=ops,
            created_by=actor_id,
        )
        return await self._changesets.save(changeset)


class ApplyChangeSet:
    """User-approved apply: the ChangeSet becomes journal ops + a checkpoint
    (audit + history preserved; the AI write never skips this path)."""

    def __init__(
        self,
        changesets: ChangeSetRepository,
        resources: Any,
        journal: Any,
        checkpoints: Any,
        ownership: ReadOnlyResourceOwnershipPort,
    ) -> None:
        self._changesets = changesets
        self._resources = resources
        self._journal = journal
        self._checkpoints = checkpoints
        self._ownership = ownership

    async def execute(
        self,
        actor_id: UUID,
        changeset_id: UUID,
    ) -> int:
        changeset = await self._changesets.find_by_id(changeset_id)
        if changeset is None:
            raise LookupError("changeset not found")
        if not await self._ownership.authorize(
            actor_id, changeset.resource_id, "resource.update"
        ):
            raise ChangesetError("no resource.update permission")
        if changeset.status is not ChangesetStatus.PROPOSED:
            return await self._journal.max_seq(changeset.resource_id)
        payload = (
            __import__("json")
            .dumps({"kind": "ai.change", "ops": changeset.ops}, default=str)
            .encode()
        )
        seq = (await self._journal.max_seq(changeset.resource_id)) + 1
        await self._journal.append_op(
            changeset.resource_id,
            seq,
            1,
            payload,
            __import__("hashlib").sha256(payload).hexdigest(),
        )
        await self._checkpoints.write(
            changeset.resource_id,
            seq,
            {"ai": True, "instruction": changeset.instruction},
        )
        await self._changesets.mark_applied(changeset_id, applied_at=datetime.now(UTC))
        return seq
