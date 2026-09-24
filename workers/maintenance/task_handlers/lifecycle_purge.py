from __future__ import annotations

from typing import Protocol
from uuid import UUID

from app_core.workspace.application.purge import (
    FatalPurgeError,
    PurgeWorkspace,
    RetryablePurgeError,
)
from app_core.workspace.ports.purge import purge_effect_key
from task_runtime.domain import RetryableTaskError


class _Task(Protocol):
    task_id: UUID
    input_ref: str | None


class _Context(Protocol):
    task: _Task
    attempt_id: UUID
    execution_epoch: int

    async def checkpoint(self) -> None: ...


class _Effects(Protocol):
    async def record_effect(self, *args: object, **kwargs: object) -> object: ...


class LifecyclePurgeHandler:
    """Domain consumer for lifecycle purge tasks.

    The generic task-runtime registry remains domain-free; this handler is
    registered by the maintenance worker package.
    """

    def __init__(self, purge: PurgeWorkspace, effects: _Effects) -> None:
        self._purge = purge
        self._effects = effects

    async def execute(self, context: _Context) -> None:
        await context.checkpoint()
        workspace_id = _workspace_id(context)
        try:
            result = await self._purge.execute(workspace_id)
        except RetryablePurgeError as exc:
            raise RetryableTaskError("purge-conflict") from exc
        except FatalPurgeError:
            raise
        await context.checkpoint()
        await self._effects.record_effect(
            context.task.task_id,
            purge_effect_key(workspace_id),
            "lifecycle.purge.workspace",
            {"workspaceId": str(workspace_id), "disposition": result.disposition},
            attempt_id=context.attempt_id,
            execution_epoch=context.execution_epoch,
        )


def _workspace_id(context: _Context) -> UUID:
    value = getattr(context.task, "input_ref", None)
    if value is None:
        raise ValueError("lifecycle purge task has no workspace identity")
    try:
        return UUID(value)
    except ValueError as exc:
        raise ValueError("lifecycle purge task has invalid workspace identity") from exc
