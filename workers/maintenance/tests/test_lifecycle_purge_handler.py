from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4

import pytest
from app_core.workspace.application.purge import (
    FatalPurgeError,
    RetryablePurgeError,
)
from task_runtime.domain import RetryableTaskError

from workers.maintenance.task_handlers.lifecycle_purge import LifecyclePurgeHandler


class Context:
    def __init__(self) -> None:
        self.task = SimpleNamespace(task_id=uuid4(), input_ref=str(uuid4()))
        self.attempt_id = uuid4()
        self.execution_epoch = 4
        self.checkpoints = 0
        self.progress: list[tuple[str | None, str | None]] = []

    async def checkpoint(self) -> None:
        self.checkpoints += 1

    async def report_progress(
        self, *, stage: str | None = None, message_code: str | None = None
    ) -> None:
        self.progress.append((stage, message_code))


class Purge:
    async def execute(self, workspace_id):
        return SimpleNamespace(disposition="Purged")


class Effects:
    def __init__(self) -> None:
        self.calls: list[tuple[tuple[object, ...], dict[str, object]]] = []

    async def record_effect(self, *args, **kwargs) -> None:
        self.calls.append((args, kwargs))


@pytest.mark.asyncio
async def test_handler_purges_and_records_fenced_effect() -> None:
    context = Context()
    effects = Effects()
    await LifecyclePurgeHandler(Purge(), effects).execute(context)  # type: ignore[arg-type]
    assert context.checkpoints == 2
    assert context.progress == [
        ("purging", "lifecycle.purge.workspace.running"),
        ("completed", "lifecycle.purge.workspace.completed"),
    ]
    assert len(effects.calls) == 1
    assert effects.calls[0][1]["attempt_id"] == context.attempt_id
    assert effects.calls[0][1]["execution_epoch"] == 4


@pytest.mark.asyncio
async def test_handler_maps_transient_failure_to_retryable() -> None:
    class Transient:
        async def execute(self, workspace_id):
            raise RetryablePurgeError("lock timeout")

    with pytest.raises(RetryableTaskError):
        await LifecyclePurgeHandler(Transient(), Effects()).execute(Context())  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_handler_preserves_fatal_failure() -> None:
    class Fatal:
        async def execute(self, workspace_id):
            raise FatalPurgeError("invalid owner")

    with pytest.raises(FatalPurgeError):
        await LifecyclePurgeHandler(Fatal(), Effects()).execute(Context())  # type: ignore[arg-type]
