from __future__ import annotations

from uuid import uuid4

import pytest
from app_core.resource.application import (
    AppendJournalOp,
    CheckpointResource,
    CreateResource,
    ReadJournal,
    RestoreAtRevision,
)
from app_core.resource.domain import (
    DuplicateJournalSeqError,
    JournalOp,
    JournalSequenceConflictError,
    Resource,
    ResourceLifecycle,
    ResourceNameConflictError,
    ResourcePermissionDeniedError,
)
from app_core.resource.ports import (
    CheckpointRepository,
    JournalRepository,
    ReadOnlyResourceOwnershipPort,
    ResourceRepository,
)


class _Repo(ResourceRepository):
    def __init__(self) -> None:
        self.rows: dict = {}
        self.siblings: set = set()

    async def create(self, resource: Resource) -> Resource:
        self.rows[str(resource.resource_id)] = resource
        self.siblings.add((str(resource.project_id), resource.normalized_name))
        return resource

    async def get(self, resource_id):
        return self.rows.get(str(resource_id))

    async def rename(self, resource_id, name, normalized_name):
        r = self.rows[str(resource_id)]
        updated = Resource(
            r.resource_id,
            r.project_id,
            r.folder_id,
            r.resource_type,
            name,
            normalized_name,
            r.lifecycle,
        )
        self.rows[str(resource_id)] = updated
        return updated

    async def set_lifecycle(self, resource_id, lifecycle):
        r = self.rows[str(resource_id)]
        updated = Resource(
            r.resource_id,
            r.project_id,
            r.folder_id,
            r.resource_type,
            r.name,
            r.normalized_name,
            ResourceLifecycle(lifecycle),
        )
        self.rows[str(resource_id)] = updated
        return updated

    async def sibling_exists(self, project_id, normalized_name):
        return (str(project_id), normalized_name) in self.siblings


class _Journal(JournalRepository):
    def __init__(self) -> None:
        self.ops: list[JournalOp] = []

    async def append_op(
        self,
        resource_id,
        seq,
        epoch,
        update_bytes,
        update_hash,
        *,
        expected_seq=None,
    ):
        if any(o.journal_seq == seq for o in self.ops):
            raise DuplicateJournalSeqError(str(seq))
        op = JournalOp(resource_id, seq, epoch, update_bytes, update_hash)
        self.ops.append(op)
        return op

    async def read_cursor(self, resource_id, after_seq, *, limit=200):
        return [o for o in self.ops if o.journal_seq > after_seq][:limit]

    async def max_seq(self, resource_id):
        return max((o.journal_seq for o in self.ops), default=0)

    async def mark_durable(self, resource_id, journal_seq):
        return None


class _Checkpoints(CheckpointRepository):
    def __init__(self) -> None:
        self.items: list = []
        self.truncated: int = 0

    async def write(self, resource_id, base_journal_seq, snapshot, created_by=None):
        seq = len(self.items) + 1
        cp = type(
            "CK",
            (),
            {
                "resource_id": resource_id,
                "checkpoint_seq": seq,
                "base_journal_seq": base_journal_seq,
                "snapshot": dict(snapshot),
                "created_at": None,
                "_seq": seq,
            },
        )()
        self.items.append(cp)
        return cp

    async def latest(self, resource_id):
        matching = [c for c in self.items if c.resource_id == resource_id]
        return matching[-1] if matching else None

    async def truncate_before(self, resource_id, journal_seq):
        self.truncated = journal_seq
        return journal_seq


class _Owner(ReadOnlyResourceOwnershipPort):
    def __init__(self, allow: bool = True) -> None:
        self.allow = allow
        self.calls: list[str] = []

    async def authorize(self, actor_id, scope_id, operation):
        self.calls.append(operation)
        return self.allow


class _JournalIdempotency:
    def __init__(self) -> None:
        self.records: dict[str, tuple[str, JournalOp]] = {}

    async def execute(self, key, fingerprint, operation):
        prior = self.records.get(key)
        if prior is not None:
            if prior[0] != fingerprint:
                from app_core.common.exceptions import IdempotencyConflictError

                raise IdempotencyConflictError()
            return prior[1]
        result = await operation()
        self.records[key] = (fingerprint, result)
        return result


def _resource(project_id=None, name="Note"):
    return Resource(
        resource_id=uuid4(),
        project_id=project_id or uuid4(),
        folder_id=None,
        resource_type="document",
        name=name,
        normalized_name=name.casefold(),
        lifecycle=ResourceLifecycle.ACTIVE,
    )


@pytest.mark.asyncio
async def test_create_resource_denies_without_permission() -> None:
    owner = _Owner(allow=False)
    use_case = CreateResource(_Repo(), owner)
    with pytest.raises(ResourcePermissionDeniedError):
        await use_case.execute(
            uuid4(), project_id=uuid4(), resource_type="document", name="A"
        )


@pytest.mark.asyncio
async def test_create_resource_sibling_conflict_and_authz_call() -> None:
    repo = _Repo()
    owner = _Owner()
    use_case = CreateResource(repo, owner)
    project_id = uuid4()
    await use_case.execute(
        uuid4(), project_id=project_id, resource_type="text", name="Shared"
    )
    with pytest.raises(ResourceNameConflictError):
        await use_case.execute(
            uuid4(), project_id=project_id, resource_type="text", name="shared"
        )
    assert owner.calls == ["resource.create", "resource.create"]
    assert "resource.create" in owner.calls


@pytest.mark.asyncio
async def test_append_journal_monotonic_and_duplicate() -> None:
    journal = _Journal()
    owner = _Owner()
    repo = _Repo()
    use_case = AppendJournalOp(repo, journal, owner)
    resource_id = uuid4()
    repo.rows[str(resource_id)] = _resource(project_id=uuid4())
    first = await use_case.execute(uuid4(), resource_id, b"op", ownership_epoch=3)
    second = await use_case.execute(uuid4(), resource_id, b"op2", ownership_epoch=3)
    assert first.journal_seq == 1 and second.journal_seq == 2
    assert owner.calls == ["resource.update", "resource.update"]
    with pytest.raises(DuplicateJournalSeqError):
        await journal.append_op(resource_id, 1, 3, b"dup", "h")


@pytest.mark.asyncio
async def test_append_journal_uses_idempotency_and_expected_sequence() -> None:
    repo = _Repo()
    journal = _Journal()
    resource_id = uuid4()
    repo.rows[str(resource_id)] = _resource(project_id=uuid4())
    owner = _Owner()
    use_case = AppendJournalOp(
        repo,
        journal,
        owner,
        idempotency=_JournalIdempotency(),
    )
    actor_id = uuid4()
    first = await use_case.execute(
        actor_id,
        resource_id,
        b"same update",
        ownership_epoch=1,
        expected_seq=1,
        idempotency_key="retry-1",
    )
    replay = await use_case.execute(
        actor_id,
        resource_id,
        b"same update",
        ownership_epoch=1,
        expected_seq=1,
        idempotency_key="retry-1",
    )
    assert replay.journal_seq == first.journal_seq == 1
    assert len(journal.ops) == 1
    assert owner.calls == ["resource.update", "resource.update"]

    with pytest.raises(JournalSequenceConflictError):
        await use_case.execute(
            actor_id,
            resource_id,
            b"another update",
            ownership_epoch=1,
            expected_seq=1,
            idempotency_key="retry-2",
        )


@pytest.mark.asyncio
async def test_checkpoint_truncate_and_restore_revision() -> None:
    journal = _Journal()
    checkpoints = _Checkpoints()
    owner = _Owner()
    resource_id = uuid4()
    repo = _Repo()
    repo.rows[str(resource_id)] = _resource(project_id=uuid4())
    append = AppendJournalOp(repo, journal, owner)
    await append.execute(uuid4(), resource_id, b"c", ownership_epoch=1)
    await append.execute(uuid4(), resource_id, b"d", ownership_epoch=1)
    checkpoint = await CheckpointResource(journal, checkpoints).execute(
        resource_id, {"x": 1}, truncate_after=True
    )
    assert checkpoint.base_journal_seq == 2
    assert checkpoints.truncated == 2
    restore = RestoreAtRevision(
        journal,
        checkpoints,
        apply=lambda state, op: {**state, "op": op.journal_seq},
    )
    state = await restore.execute(resource_id, 2)
    assert state["x"] == 1  # snapshot materialized


@pytest.mark.asyncio
async def test_restore_revision_reports_coalesced_replay_progress() -> None:
    journal = _Journal()
    resource_id = uuid4()
    journal.ops = [JournalOp(resource_id, seq, 1, b"", "") for seq in range(1, 102)]
    progress: list[tuple[int, int]] = []

    async def report(current: int, total: int) -> None:
        progress.append((current, total))

    restore = RestoreAtRevision(
        journal,
        _Checkpoints(),
        apply=lambda state, op: {**state, "seq": op.journal_seq},
    )
    state = await restore.execute(resource_id, 101, on_progress=report)

    assert state["seq"] == 101
    assert progress == [(0, 101), (100, 101), (101, 101)]


@pytest.mark.asyncio
async def test_read_journal_cursor() -> None:
    journal = _Journal()
    owner = _Owner()
    resource_id = uuid4()
    repo = _Repo()
    repo.rows[str(resource_id)] = _resource(project_id=uuid4())
    append = AppendJournalOp(repo, journal, owner)
    await append.execute(uuid4(), resource_id, b"a", ownership_epoch=1)
    await append.execute(uuid4(), resource_id, b"b", ownership_epoch=1)
    ops = await ReadJournal(journal).execute(resource_id, after_seq=1)
    assert [o.journal_seq for o in ops] == [2]
