from __future__ import annotations

from typing import Any, Protocol
from uuid import UUID

from app_core.history.application import RestoreAtVersion
from app_core.history.reduce import reduce_ops
from app_core.resource.domain import ResourceLifecycle

TASK_TYPE = "history.restore"
INPUT_REF_PREFIX = "history.restore:v1"


class _Task(Protocol):
    task_id: UUID
    actor_account_id: UUID | None
    resource_id: UUID | None
    input_ref: str | None


class _Context(Protocol):
    task: _Task

    async def checkpoint(self) -> None: ...

    async def report_progress(
        self,
        *,
        stage: str | None = None,
        message_code: str | None = None,
        current: int | None = None,
        total: int | None = None,
    ) -> None: ...


class _ResourceReader(Protocol):
    async def get(self, resource_id: UUID) -> Any | None: ...


class _JournalReader(Protocol):
    async def max_seq(self, resource_id: UUID) -> int: ...


class _Ownership(Protocol):
    async def authorize(
        self, actor_id: UUID, scope_id: UUID, operation: str
    ) -> bool: ...


class HistoryRestoreHandler:
    """Execute a queued History Restore after rechecking current authority."""

    def __init__(
        self,
        resources: _ResourceReader,
        ownership: _Ownership,
        journal: _JournalReader,
        restore: RestoreAtVersion,
    ) -> None:
        self._resources = resources
        self._ownership = ownership
        self._journal = journal
        self._restore = restore

    async def execute(self, context: _Context) -> None:
        await context.checkpoint()
        resource_id, target_seq = parse_input_ref(context.task.input_ref)
        actor_id = context.task.actor_account_id
        if actor_id is None:
            raise ValueError("history restore task has no initiating actor")
        if context.task.resource_id != resource_id:
            raise ValueError("history restore task resource does not match input")
        if not await self._ownership.authorize(
            actor_id, resource_id, "resource.update"
        ):
            raise PermissionError("history restore actor no longer has resource.update")
        resource = await self._resources.get(resource_id)
        if resource is None:
            raise LookupError("history restore resource no longer exists")
        if resource.lifecycle is not ResourceLifecycle.ACTIVE:
            raise ValueError("history restore resource is not active")
        if target_seq > await self._journal.max_seq(resource_id):
            raise LookupError("history restore version no longer exists")

        # Cancellation/lease ownership can change while the authorization reads run.
        await context.checkpoint()

        async def report_progress(
            stage: str, current: int | None, total: int | None
        ) -> None:
            await context.report_progress(
                stage=stage,
                message_code=f"history.restore.{stage}",
                current=current,
                total=total,
            )

        await report_progress("preparing", None, None)
        await self._restore.execute(
            resource_id,
            target_seq,
            actor_id=actor_id,
            on_progress=report_progress,
        )


def parse_input_ref(value: str | None) -> tuple[UUID, int]:
    if value is None:
        raise ValueError("history restore task has no input reference")
    prefix = f"{INPUT_REF_PREFIX}:"
    if not value.startswith(prefix):
        raise ValueError("history restore task input reference has invalid version")
    parts = value[len(prefix) :].split(":")
    if len(parts) != 2:
        raise ValueError("history restore task input reference is malformed")
    try:
        resource_id = UUID(parts[0])
        target_seq = int(parts[1])
    except ValueError as exc:
        raise ValueError("history restore task input reference is malformed") from exc
    if target_seq < 1 or str(resource_id) != parts[0] or str(target_seq) != parts[1]:
        raise ValueError("history restore task input reference is not canonical")
    return resource_id, target_seq


def input_ref(resource_id: UUID, target_seq: int) -> str:
    if target_seq < 1:
        raise ValueError("target sequence must be positive")
    return f"{INPUT_REF_PREFIX}:{resource_id}:{target_seq}"


def apply_history_op(state: dict[str, Any], op: object) -> dict[str, Any]:
    return reduce_ops(state, [op])  # type: ignore[list-item]
