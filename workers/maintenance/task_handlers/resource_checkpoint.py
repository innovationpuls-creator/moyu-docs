from __future__ import annotations

from typing import Callable, Protocol
from uuid import UUID

from app_core.resource.application import CheckpointResource
from app_core.resource.ports import ResourceRepository
from task_runtime.domain import RetryableTaskError


class _Task(Protocol):
    task_id: UUID
    input_ref: str | None


class _Context(Protocol):
    task: _Task
    attempt_id: UUID
    execution_epoch: int

    async def checkpoint(self) -> None: ...

    async def report_progress(
        self,
        *,
        stage: str | None = None,
        message_code: str | None = None,
        current: int | None = None,
        total: int | None = None,
    ) -> None: ...


class _Journal(Protocol):
    async def max_seq(self, resource_id: UUID) -> int: ...


class _Effects(Protocol):
    async def record_effect(self, *args: object, **kwargs: object) -> object: ...


ResourceCheckpointed = Callable[[UUID, int], dict]


class _ProjectReader(Protocol):
    async def find_by_id(self, project_id: UUID) -> object | None: ...


class _SearchIndex(Protocol):
    async def upsert(
        self,
        *,
        resource_id: UUID,
        workspace_id: UUID,
        project_id: UUID,
        resource_type: str,
        name: str,
        searchable_text: str,
        lifecycle: str,
    ) -> None: ...


class ResourceCheckpointHandler:
    """Task consumer: checkpoints a Resource through the Core application.

    Snapshot for this slice is a metadata marker (resourceId + baseJournalSeq) or
    a consumer-injected materializer; journal truncation stays under the
    CheckpointResource retention policy (default: keep journal).
    """

    def __init__(
        self,
        journal: _Journal,
        checkpoints: object,
        effects: _Effects,
        *,
        materialize: ResourceCheckpointed | None = None,
        search_index: _SearchIndex | None = None,
        resources: ResourceRepository | None = None,
        projects: _ProjectReader | None = None,
    ) -> None:
        self._journal = journal
        self._checkpoint = CheckpointResource(journal, checkpoints)  # type: ignore[arg-type]
        self._effects = effects
        self._materialize = materialize or (
            lambda resource_id, base_seq: {
                "resourceId": str(resource_id),
                "baseJournalSeq": base_seq,
            }
        )
        self._search_index = search_index
        self._resources = resources
        self._projects = projects

    async def execute(self, context: _Context) -> None:
        await context.checkpoint()
        resource_id = _resource_id(context)
        await context.report_progress(
            stage="checkpointing", message_code="resource.checkpoint.running"
        )
        base_seq = await self._journal_max(context)
        snapshot = self._materialize(resource_id, base_seq)
        try:
            saved = await self._checkpoint.execute(
                resource_id, snapshot, truncate_after=False
            )
        except Exception as exc:  # transient DB conflicts -> retryable
            raise RetryableTaskError("checkpoint-conflict") from exc
        await context.checkpoint()
        if (
            self._search_index is not None
            and self._resources is not None
            and isinstance(snapshot, dict)
            and snapshot.get("text")
        ):
            row = await self._resources.get(resource_id)
            if row is not None and self._projects is not None:
                project = await self._projects.find_by_id(row.project_id)
                workspace_id = (
                    project.workspace_id  # type: ignore[attr-defined]
                    if project is not None
                    else row.project_id
                )
                await self._search_index.upsert(
                    resource_id=resource_id,
                    workspace_id=workspace_id,
                    project_id=row.project_id,
                    resource_type=row.resource_type,
                    name=row.name,
                    searchable_text=str(snapshot.get("text")),
                    lifecycle=row.lifecycle,
                )
        await self._effects.record_effect(
            context.task.task_id,
            f"resource.checkpoint:{resource_id}",
            "resource.checkpoint",
            {"resourceId": str(resource_id), "baseJournalSeq": saved.base_journal_seq},
            attempt_id=context.attempt_id,
            execution_epoch=context.execution_epoch,
        )
        await context.report_progress(
            stage="completed", message_code="resource.checkpoint.completed"
        )

    async def _journal_max(self, context: _Context) -> int:
        return await self._journal.max_seq(_resource_id(context))


def _resource_id(context: _Context) -> UUID:
    value = getattr(context.task, "input_ref", None)
    if value is None:
        raise ValueError("resource checkpoint task has no resource identity")
    return UUID(value)
