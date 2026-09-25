from __future__ import annotations

from types import SimpleNamespace
from typing import Any, cast
from uuid import UUID, uuid4

import pytest
from app_core.history.application import RestoreAtVersion
from app_core.resource.domain import ResourceLifecycle

from workers.maintenance.task_handlers.history_restore import (
    HistoryRestoreHandler,
    input_ref,
    parse_input_ref,
)


class _Context:
    def __init__(self, task: Any) -> None:
        self.task = task
        self.checkpoints = 0
        self.progress: list[tuple[str | None, str | None, int | None, int | None]] = []

    async def checkpoint(self) -> None:
        self.checkpoints += 1

    async def report_progress(
        self, *, stage=None, message_code=None, current=None, total=None
    ) -> None:
        self.progress.append((stage, message_code, current, total))


class _ResourceReader:
    def __init__(self, lifecycle: ResourceLifecycle) -> None:
        self.lifecycle = lifecycle

    async def get(self, _resource_id: UUID) -> Any:
        return SimpleNamespace(lifecycle=self.lifecycle)


class _JournalReader:
    async def max_seq(self, _resource_id: UUID) -> int:
        return 7


class _Ownership:
    def __init__(self, allowed: bool) -> None:
        self.allowed = allowed
        self.calls: list[tuple[UUID, UUID, str]] = []

    async def authorize(
        self, actor_id: UUID, resource_id: UUID, operation: str
    ) -> bool:
        self.calls.append((actor_id, resource_id, operation))
        return self.allowed


class _Restore:
    def __init__(self) -> None:
        self.calls: list[tuple[UUID, int, UUID | None]] = []

    async def execute(
        self,
        resource_id: UUID,
        target_seq: int,
        *,
        actor_id: UUID | None,
        on_progress=None,
    ) -> tuple[int, object]:
        self.calls.append((resource_id, target_seq, actor_id))
        if on_progress is not None:
            await on_progress("materializing", None, None)
            await on_progress("replaying", 0, 0)
            await on_progress("saving", 0, 0)
        return 8, object()


def _context(resource_id: UUID, actor_id: UUID, target_seq: int = 7) -> _Context:
    return _Context(
        SimpleNamespace(
            task_id=uuid4(),
            actor_account_id=actor_id,
            resource_id=resource_id,
            input_ref=input_ref(resource_id, target_seq),
        )
    )


def test_input_ref_is_a_canonical_resource_version_identity() -> None:
    resource_id = uuid4()
    encoded = input_ref(resource_id, 7)

    assert parse_input_ref(encoded) == (resource_id, 7)
    with pytest.raises(ValueError):
        parse_input_ref(encoded.upper())


@pytest.mark.asyncio
async def test_handler_rechecks_permission_before_restore() -> None:
    resource_id = uuid4()
    actor_id = uuid4()
    context = _context(resource_id, actor_id)
    ownership = _Ownership(allowed=False)
    restore = _Restore()
    handler = HistoryRestoreHandler(
        _ResourceReader(ResourceLifecycle.ACTIVE),
        ownership,
        _JournalReader(),
        cast(RestoreAtVersion, restore),
    )

    with pytest.raises(PermissionError):
        await handler.execute(context)

    assert context.checkpoints == 1
    assert ownership.calls == [(actor_id, resource_id, "resource.update")]
    assert restore.calls == []


@pytest.mark.asyncio
async def test_handler_rechecks_lifecycle_before_restore() -> None:
    resource_id = uuid4()
    actor_id = uuid4()
    context = _context(resource_id, actor_id)
    restore = _Restore()
    handler = HistoryRestoreHandler(
        _ResourceReader(ResourceLifecycle.TRASHED),
        _Ownership(allowed=True),
        _JournalReader(),
        cast(RestoreAtVersion, restore),
    )

    with pytest.raises(ValueError, match="not active"):
        await handler.execute(context)

    assert context.checkpoints == 1
    assert restore.calls == []


@pytest.mark.asyncio
async def test_handler_rejects_version_after_current_journal() -> None:
    resource_id = uuid4()
    actor_id = uuid4()
    context = _context(resource_id, actor_id, target_seq=8)
    restore = _Restore()
    handler = HistoryRestoreHandler(
        _ResourceReader(ResourceLifecycle.ACTIVE),
        _Ownership(allowed=True),
        _JournalReader(),
        cast(RestoreAtVersion, restore),
    )

    with pytest.raises(LookupError, match="no longer exists"):
        await handler.execute(context)

    assert context.checkpoints == 1
    assert restore.calls == []


@pytest.mark.asyncio
async def test_handler_applies_restore_as_initiating_actor() -> None:
    resource_id = uuid4()
    actor_id = uuid4()
    context = _context(resource_id, actor_id)
    restore = _Restore()
    handler = HistoryRestoreHandler(
        _ResourceReader(ResourceLifecycle.ACTIVE),
        _Ownership(allowed=True),
        _JournalReader(),
        cast(RestoreAtVersion, restore),
    )

    await handler.execute(context)

    assert context.checkpoints == 2
    assert restore.calls == [(resource_id, 7, actor_id)]
    assert [progress[0] for progress in context.progress] == [
        "preparing",
        "materializing",
        "replaying",
        "saving",
    ]
    assert context.progress[2] == ("replaying", "history.restore.replaying", 0, 0)
