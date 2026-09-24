from __future__ import annotations

from typing import Protocol
from uuid import UUID

from app_core.resource.purge import (
    FatalPurgeError,
    PurgeResource,
    RetryablePurgeError,
    purge_effect_key,
)
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


class _Audit(Protocol):
    async def record(
        self,
        *,
        actor_account_id: UUID | None,
        action: str,
        target_type: str,
        target_id: UUID | None,
        detail: dict | None = None,
    ) -> None: ...


class ResourcePurgeHandler:
    """Task consumer: physically purges an expired Trashed Resource."""

    def __init__(
        self, purge: PurgeResource, effects: _Effects, audit: _Audit | None = None
    ) -> None:
        self._purge = purge
        self._effects = effects
        self._audit = audit

    async def execute(self, context: _Context) -> None:
        await context.checkpoint()
        resource_id = _resource_id(context)
        try:
            purged = await self._purge.execute(resource_id)
        except RetryablePurgeError as exc:
            raise RetryableTaskError("purge-conflict") from exc
        except FatalPurgeError:
            raise
        await context.checkpoint()
        if self._audit is not None:
            await self._audit.record(
                actor_account_id=None,
                action="resource.purged",
                target_type="resource",
                target_id=resource_id,
                detail={"purged": purged},
            )
        await self._effects.record_effect(
            context.task.task_id,
            purge_effect_key(resource_id),
            "lifecycle.purge.resource",
            {"resourceId": str(resource_id), "purged": purged},
            attempt_id=context.attempt_id,
            execution_epoch=context.execution_epoch,
        )


def _resource_id(context: _Context) -> UUID:
    value = getattr(context.task, "input_ref", None)
    if value is None:
        raise ValueError("resource purge task has no resource identity")
    return UUID(value)
