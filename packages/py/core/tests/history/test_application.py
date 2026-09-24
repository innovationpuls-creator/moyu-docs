from __future__ import annotations

from uuid import uuid4

import pytest
from app_core.history.application import (
    CreateNamedVersion,
    ListVersions,
    RestoreAtVersion,
)
from app_core.history.domain import (
    NamedVersion,
    NamedVersionLabelConflictError,
    VersionKind,
    VersionNode,
)
from app_core.history.ports import HistoryRepository
from app_core.resource.domain import (
    Resource,
    ResourceLifecycle,
)


class _History(HistoryRepository):
    def __init__(self) -> None:
        self.nodes: list[VersionNode] = []
        self.named: dict = {}
        self.labels: set = set()

    async def list_nodes(self, resource_id, *, limit=100):
        return self.nodes[:limit]

    async def create_named_version(
        self, resource_id, label, base_journal_seq, created_by
    ):
        v = NamedVersion(
            uuid4(), resource_id, label, base_journal_seq, created_by, None
        )
        self.named[label] = v
        self.labels.add(label)
        self.nodes.append(
            VersionNode(
                v.version_id,
                resource_id,
                VersionKind.NAMED,
                label,
                created_by,
                None,
                base_journal_seq,
            )
        )
        return v

    async def named_label_exists(self, resource_id, label):
        return label in self.labels


class _Journal:
    def __init__(self) -> None:
        self.seq = 0

    async def max_seq(self, resource_id):
        return self.seq

    async def append_op(self, resource_id, seq, epoch, update_bytes, update_hash):
        from app_core.resource.domain import JournalOp

        self.seq = seq
        return JournalOp(resource_id, seq, epoch, update_bytes, update_hash)

    async def read_cursor(self, resource_id, after_seq, *, limit=200):
        return []


class _Checkpoints:
    def __init__(self) -> None:
        self.latest_ck = None

    async def write(self, resource_id, base_journal_seq, snapshot, created_by=None):
        ck = type(
            "CK",
            (),
            {
                "resource_id": resource_id,
                "base_journal_seq": base_journal_seq,
                "snapshot": dict(snapshot),
                "created_at": None,
                "checkpoint_seq": 1,
            },
        )()
        self.latest_ck = ck
        return ck

    async def latest(self, resource_id):
        return self.latest_ck


class _Resources:
    def __init__(self) -> None:
        self.row = Resource(
            uuid4(),
            uuid4(),
            None,
            "document",
            "D",
            "d",
            ResourceLifecycle.ACTIVE,
        )

    async def get(self, resource_id):
        return self.row


@pytest.mark.asyncio
async def test_create_named_version_and_label_conflict() -> None:
    history = _History()
    create = CreateNamedVersion(history)
    resource_id = uuid4()
    version = await create.execute(resource_id, "API 确认", base_journal_seq=3)
    assert version.label == "API 确认"
    with pytest.raises(NamedVersionLabelConflictError):
        await create.execute(resource_id, "API 确认", base_journal_seq=4)
    assert len(await ListVersions(history).execute(resource_id)) == 1


@pytest.mark.asyncio
async def test_restore_is_a_new_modification_not_a_rewind() -> None:
    history = _History()
    journal = _Journal()
    checkpoints = _Checkpoints()
    resources = _Resources()
    restore = RestoreAtVersion(
        history,
        resources,
        journal,
        checkpoints,
        apply=lambda state, op: {**state, "seq": op.journal_seq},
    )
    node = await restore.execute(
        resources.row.resource_id, target_seq=8, actor_id=uuid4()
    )
    assert node.kind == VersionKind.RESTORE
    assert node.base_journal_seq == 1  # new current (9th seq -> max+1 in real chain)
    assert node.summary and "restored" in node.summary
    # previous current remains accessible: latest checkpoint before restore kept
    assert checkpoints.latest_ck is not None
