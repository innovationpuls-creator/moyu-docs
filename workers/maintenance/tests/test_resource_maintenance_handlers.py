from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4

import pytest
from app_core.resource.domain import Checkpoint

from workers.maintenance.task_handlers.resource_checkpoint import (
    ResourceCheckpointHandler,
)
from workers.maintenance.task_handlers.resource_purge import ResourcePurgeHandler


class _Context:
    def __init__(self) -> None:
        self.task = SimpleNamespace(task_id=uuid4(), input_ref=str(uuid4()))
        self.attempt_id = uuid4()
        self.execution_epoch = 2
        self.progress: list[tuple[str | None, str | None, int | None, int | None]] = []

    async def checkpoint(self) -> None:
        return None

    async def report_progress(
        self,
        *,
        stage: str | None = None,
        message_code: str | None = None,
        current: int | None = None,
        total: int | None = None,
    ) -> None:
        self.progress.append((stage, message_code, current, total))


class _Effects:
    def __init__(self) -> None:
        self.calls: list[tuple[tuple[object, ...], dict[str, object]]] = []

    async def record_effect(self, *args: object, **kwargs: object) -> None:
        self.calls.append((args, kwargs))


@pytest.mark.asyncio
async def test_resource_purge_reports_start_and_completion_without_percent() -> None:
    class _Purge:
        async def execute(self, _resource_id):
            return True

    context = _Context()
    effects = _Effects()

    await ResourcePurgeHandler(_Purge(), effects).execute(context)  # type: ignore[arg-type]

    assert context.progress == [
        ("purging", "resource.purge.running", None, None),
        ("completed", "resource.purge.completed", None, None),
    ]
    assert len(effects.calls) == 1


@pytest.mark.asyncio
async def test_checkpoint_reports_progress_without_percent() -> None:
    class _Journal:
        async def max_seq(self, _resource_id):
            return 7

    class _Checkpoints:
        async def write(self, resource_id, base_journal_seq, snapshot, **_kwargs):
            return Checkpoint(
                resource_id=resource_id,
                checkpoint_seq=base_journal_seq,
                base_journal_seq=base_journal_seq,
                snapshot=snapshot,
            )

    context = _Context()
    effects = _Effects()
    handler = ResourceCheckpointHandler(_Journal(), _Checkpoints(), effects)

    await handler.execute(context)  # type: ignore[arg-type]

    assert context.progress == [
        ("checkpointing", "resource.checkpoint.running", None, None),
        ("completed", "resource.checkpoint.completed", None, None),
    ]
    assert len(effects.calls) == 1
