from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

import pytest
from app_core.ai.application import ApplyChangeSet, ProposeChangeSet
from app_core.ai.domain import ChangeSet, ChangesetStatus
from app_core.resource.domain import (
    JournalSequenceConflictError,
    ResourceContent,
    ResourceContentMutation,
)


class _Resources:
    async def get(self, _resource_id: UUID) -> object:
        return object()


class _Content:
    def __init__(self, journal_seq: int = 4) -> None:
        self.current = ResourceContent(
            {
                "nodes": [
                    {
                        "kind": "paragraph",
                        "children": [{"kind": "text", "text": "original"}],
                    }
                ],
                "text": "original",
            },
            journal_seq,
        )
        self.replacements: list[dict[str, object]] = []

    async def read(self, _resource_id: UUID, *, at_journal_seq=None):
        return self.current

    async def replace(self, resource_id, snapshot, **kwargs):
        self.replacements.append(
            {"resource_id": resource_id, "snapshot": snapshot, **kwargs}
        )
        self.current = ResourceContent(snapshot, self.current.journal_seq + 1)
        return ResourceContentMutation(self.current.journal_seq)


class _Provider:
    def __init__(self) -> None:
        self.snapshot: dict | None = None

    async def propose(self, _resource_id, _instruction, *, snapshot):
        self.snapshot = snapshot
        return [{"op": "summary-insert", "value": "AI summary"}]


class _ChangeSets:
    def __init__(self) -> None:
        self.saved: ChangeSet | None = None
        self.applied: tuple[UUID, int] | None = None

    async def save(self, changeset: ChangeSet) -> ChangeSet:
        self.saved = changeset
        return changeset

    async def find_by_id(self, changeset_id: UUID) -> ChangeSet | None:
        if self.saved and self.saved.changeset_id == changeset_id:
            return self.saved
        return None

    async def mark_applied(
        self, changeset_id: UUID, *, applied_at: datetime, journal_seq: int
    ) -> None:
        self.applied = (changeset_id, journal_seq)
        assert self.saved is not None
        self.saved = ChangeSet(
            **{
                **self.saved.__dict__,
                "status": ChangesetStatus.APPLIED,
                "applied_at": applied_at,
                "applied_journal_seq": journal_seq,
            }
        )


class _Ownership:
    async def authorize(self, _actor_id, _resource_id, _operation) -> bool:
        return True


@pytest.mark.asyncio
async def test_proposal_uses_current_content_and_apply_writes_yjs_intent() -> None:
    actor_id = uuid4()
    resource_id = uuid4()
    content = _Content()
    provider = _Provider()
    changesets = _ChangeSets()
    ownership = _Ownership()

    proposal = await ProposeChangeSet(
        changesets, _Resources(), content, provider, ownership
    ).execute(actor_id, resource_id, instruction="summarize")

    assert provider.snapshot == content.current.snapshot
    assert proposal.base_journal_seq == 4
    assert (
        await ApplyChangeSet(changesets, content, ownership).execute(
            actor_id, proposal.changeset_id
        )
        == 5
    )
    assert content.replacements == [
        {
            "resource_id": resource_id,
            "snapshot": {
                "nodes": [
                    {
                        "kind": "paragraph",
                        "children": [{"kind": "text", "text": "AI summary"}],
                    },
                    {
                        "kind": "paragraph",
                        "children": [{"kind": "text", "text": "original"}],
                    },
                ],
                "text": "AI summary\noriginal",
            },
            "operation_id": proposal.changeset_id,
            "created_by": actor_id,
            "reason": "ai-changeset",
            "expected_journal_seq": 4,
        }
    ]
    assert changesets.applied == (proposal.changeset_id, 5)


@pytest.mark.asyncio
async def test_apply_rejects_stale_change_set_without_replacing_content() -> None:
    actor_id = uuid4()
    resource_id = uuid4()
    content = _Content()
    changesets = _ChangeSets()
    proposal = ChangeSet(
        changeset_id=uuid4(),
        resource_id=resource_id,
        instruction="summarize",
        ops=[{"op": "summary-insert", "value": "AI summary"}],
        created_by=actor_id,
        base_journal_seq=4,
    )
    await changesets.save(proposal)
    content.current = ResourceContent(content.current.snapshot, 5)

    with pytest.raises(JournalSequenceConflictError):
        await ApplyChangeSet(changesets, content, _Ownership()).execute(
            actor_id, proposal.changeset_id
        )

    assert content.replacements == []
    assert changesets.applied is None
