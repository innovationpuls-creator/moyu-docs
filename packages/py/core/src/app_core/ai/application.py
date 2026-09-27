from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from app_core.ai.domain import ChangeSet, ChangesetError, ChangesetStatus
from app_core.ai.ports import AIChangeProvider, ChangeSetRepository
from app_core.resource.domain import JournalSequenceConflictError
from app_core.resource.ports import ReadOnlyResourceOwnershipPort, ResourceContentPort


class ProposeChangeSet:
    """Arch 12 §6: AI output never writes directly — it becomes a ChangeSet."""

    def __init__(
        self,
        changesets: ChangeSetRepository,
        resources: Any,
        content: ResourceContentPort,
        provider: AIChangeProvider,
        ownership: ReadOnlyResourceOwnershipPort,
    ) -> None:
        self._changesets = changesets
        self._resources = resources
        self._content = content
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
        base = await self._content.read(resource_id)
        ops = await self._provider.propose(
            resource_id, instruction, snapshot=base.snapshot
        )
        changeset = ChangeSet(
            changeset_id=uuid4(),
            resource_id=resource_id,
            instruction=instruction,
            ops=ops,
            created_by=actor_id,
            base_journal_seq=base.journal_seq,
        )
        return await self._changesets.save(changeset)


class ApplyChangeSet:
    """User-approved apply: the ChangeSet becomes journal ops + a checkpoint
    (audit + history preserved; the AI write never skips this path)."""

    def __init__(
        self,
        changesets: ChangeSetRepository,
        content: ResourceContentPort,
        ownership: ReadOnlyResourceOwnershipPort,
    ) -> None:
        self._changesets = changesets
        self._content = content
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
            if changeset.applied_journal_seq is None:
                raise ChangesetError("applied ChangeSet receipt is unavailable")
            return changeset.applied_journal_seq
        if changeset.base_journal_seq is None:
            raise ChangesetError("CHANGESET_BASE_STATE_UNAVAILABLE")
        current = await self._content.read(changeset.resource_id)
        if current.journal_seq != changeset.base_journal_seq:
            raise JournalSequenceConflictError(current.journal_seq + 1)
        updated_snapshot = apply_change_operations(current.snapshot, changeset.ops)
        receipt = await self._content.replace(
            changeset.resource_id,
            updated_snapshot,
            operation_id=changeset_id,
            created_by=actor_id,
            reason="ai-changeset",
            expected_journal_seq=changeset.base_journal_seq,
        )
        await self._changesets.mark_applied(
            changeset_id,
            applied_at=datetime.now(UTC),
            journal_seq=receipt.journal_seq,
        )
        return receipt.journal_seq


def apply_change_operations(
    snapshot: dict[str, Any], operations: list[dict[str, Any]]
) -> dict[str, Any]:
    nodes = list(snapshot.get("nodes") or [])
    text = snapshot.get("text")
    if not nodes and isinstance(text, str) and text:
        nodes = [
            {
                "kind": "paragraph",
                "children": [{"kind": "text", "text": line}],
            }
            for line in text.split("\n")
        ]
    for operation in operations:
        if operation.get("op") != "summary-insert":
            raise ChangesetError("CHANGESET_OPERATION_UNSUPPORTED")
        value = operation.get("value")
        if not isinstance(value, str) or not value.strip():
            raise ChangesetError("CHANGESET_OPERATION_INVALID")
        nodes.insert(
            0,
            {
                "kind": "paragraph",
                "children": [{"kind": "text", "text": value}],
            },
        )
    return {"nodes": nodes, "text": _content_text(nodes)}


def _content_text(nodes: list[dict[str, Any]]) -> str:
    from urllib.parse import quote

    parts: list[str] = []
    for node in nodes:
        kind = node.get("kind")
        if kind == "text":
            parts.append(str(node.get("text", "")))
        elif kind in {"paragraph", "heading"}:
            parts.append(
                "".join(
                    str(child.get("text", "")) for child in node.get("children", [])
                )
            )
        elif kind == "list":
            parts.append(
                "\n".join(
                    "".join(
                        str(child.get("text", ""))
                        for child in paragraph.get("children", [])
                    )
                    for paragraph in node.get("children", [])
                )
            )
        elif kind in {"image", "attachment"}:
            label = quote(str(node.get("label", "")), safe="-_.!~*'()")
            label = label.replace("%20", " ")
            asset_id = quote(str(node.get("assetId", "")), safe="-_.!~*'()")
            prefix = "!" if kind == "image" else ""
            parts.append(f"{prefix}[{label}](asset://{asset_id})")
        else:
            raise ChangesetError("CHANGESET_CONTENT_INVALID")
    return "\n".join(parts)
