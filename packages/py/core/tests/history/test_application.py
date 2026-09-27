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
    ResourceContent,
    ResourceContentMutation,
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


class _Content:
    def __init__(self) -> None:
        self.reads: list[tuple[object, int | None]] = []
        self.replacements: list[dict] = []

    async def read(self, resource_id, *, at_journal_seq=None):
        self.reads.append((resource_id, at_journal_seq))
        return ResourceContent({"nodes": [{"kind": "paragraph"}]}, at_journal_seq or 9)

    async def replace(self, resource_id, snapshot, **kwargs):
        self.replacements.append(
            {"resource_id": resource_id, "snapshot": snapshot, **kwargs}
        )
        return ResourceContentMutation(10)


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
    resources = _Resources()
    content = _Content()
    restore = RestoreAtVersion(resources, content)
    progress: list[tuple[str, int | None, int | None]] = []

    async def report(stage: str, current: int | None, total: int | None) -> None:
        progress.append((stage, current, total))

    actor_id = uuid4()
    operation_id = uuid4()
    node = await restore.execute(
        resources.row.resource_id,
        target_seq=8,
        actor_id=actor_id,
        operation_id=operation_id,
        on_progress=report,
    )
    assert node.kind == VersionKind.RESTORE
    assert node.base_journal_seq == 10
    assert node.summary and "restored" in node.summary
    assert content.reads == [(resources.row.resource_id, 8)]
    assert content.replacements == [
        {
            "resource_id": resources.row.resource_id,
            "snapshot": {"nodes": [{"kind": "paragraph"}]},
            "operation_id": operation_id,
            "created_by": actor_id,
            "reason": "history-restore",
            "restore_target_seq": 8,
        }
    ]
    assert progress == [
        ("materializing", None, None),
        ("saving", None, None),
    ]
