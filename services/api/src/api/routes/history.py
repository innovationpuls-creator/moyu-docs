from __future__ import annotations

from typing import Annotated
from uuid import UUID

from app_contracts.commands.history.create_version_restore_task import (
    CreateVersionRestoreTaskResponse,
)
from app_core.common.exceptions import ConflictError
from app_core.history.application import (
    CreateNamedVersion,
    ListVersions,
    RestoreAtVersion,
)
from app_core.history.domain import NamedVersionLabelConflictError, VersionNode
from app_core.operations.task import CreateTask
from app_core.resource.domain import ResourceLifecycle, ResourcePermissionDeniedError
from app_core.session.domain.session import Session
from app_infra.postgres.history.history_repository import (
    PostgresHistoryRepository,
)
from app_infra.postgres.resource.checkpoint_repository import (
    PostgresCheckpointRepository,
)
from app_infra.postgres.resource.journal_repository import PostgresJournalRepository
from app_infra.postgres.resource.resource_repository import (
    PostgresResourceRepository,
)
from app_infra.postgres.resource_ownership_repository import (
    PostgresResourceOwnershipRepository,
)
from app_infra.postgres.task.task_repository import PostgresTaskRepository
from fastapi import APIRouter, Depends, Header, HTTPException, Path, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from api.dependencies.auth import get_current_session, get_db_session
from api.routes.tasks import _task_summary

router = APIRouter()


class CreateVersionRequest(BaseModel):
    resourceId: UUID
    label: str
    baseJournalSeq: int


class CreateVersionResponse(BaseModel):
    resourceId: UUID
    versionId: UUID
    label: str
    baseJournalSeq: int


class HistoryItem(BaseModel):
    seq: int
    kind: str
    label: str | None
    author: str | None
    occurredAt: str | None


class HistoryResponse(BaseModel):
    resourceId: UUID
    items: list[HistoryItem]


@router.get("/resources/{resource_id}/history", response_model=HistoryResponse)
async def list_history(
    resource_id: UUID,
    current: Annotated[Session, Depends(get_current_session)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> HistoryResponse:
    try:
        await PostgresResourceOwnershipRepository(session).authorize(
            current.account_id, resource_id, "resource.read"
        )
    except ResourcePermissionDeniedError:
        raise HTTPException(status_code=403, detail="RESOURCE_PERMISSION_DENIED")
    nodes: list[VersionNode] = await ListVersions(
        PostgresHistoryRepository(session)
    ).execute(resource_id)
    return HistoryResponse(
        resourceId=resource_id,
        items=[
            HistoryItem(
                seq=n.base_journal_seq,
                kind=n.kind.value,
                label=n.label,
                author=str(n.author) if n.author else None,
                occurredAt=n.occurred_at.isoformat() if n.occurred_at else None,
            )
            for n in nodes
        ],
    )


class RestoreRequest(BaseModel):
    baseJournalSeq: int


class RestoreResponse(BaseModel):
    resourceId: UUID
    newSeq: int
    label: str


@router.post("/resources/{resource_id}/history/restore", response_model=RestoreResponse)
async def restore_version(
    resource_id: UUID,
    body: RestoreRequest,
    current: Annotated[Session, Depends(get_current_session)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> RestoreResponse:
    try:
        await PostgresResourceOwnershipRepository(session).authorize(
            current.account_id, resource_id, "resource.update"
        )
    except ResourcePermissionDeniedError:
        raise HTTPException(status_code=403, detail="RESOURCE_PERMISSION_DENIED")

    def apply(state: dict, op: object) -> dict:
        from app_core.history.reduce import reduce_ops

        return reduce_ops(state, [op])  # type: ignore[list-item]

    try:
        node = await RestoreAtVersion(
            PostgresHistoryRepository(session),
            PostgresResourceRepository(session),
            PostgresJournalRepository(session),
            PostgresCheckpointRepository(session),
            apply,
        ).execute(resource_id, body.baseJournalSeq, actor_id=current.account_id)
    except LookupError:
        raise HTTPException(status_code=404, detail="RESOURCE_NOT_FOUND")
    return RestoreResponse(
        resourceId=resource_id,
        newSeq=node.base_journal_seq,
        label=node.label or "",
    )


@router.post(
    "/resources/{resource_id}/versions/{base_journal_seq}/restore-tasks",
    response_model=CreateVersionRestoreTaskResponse,
    status_code=status.HTTP_202_ACCEPTED,
    operation_id="CreateVersionRestoreTask",
)
async def create_version_restore_task(
    resource_id: UUID,
    base_journal_seq: Annotated[int, Path(ge=1)],
    current: Annotated[Session, Depends(get_current_session)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
    idempotency_key: Annotated[UUID, Header(alias="Idempotency-Key")],
) -> CreateVersionRestoreTaskResponse:
    resources = PostgresResourceRepository(session)
    resource = await resources.get(resource_id)
    if resource is None:
        raise HTTPException(status_code=404, detail="RESOURCE_NOT_FOUND")
    if not await PostgresResourceOwnershipRepository(session).authorize(
        current.account_id, resource_id, "resource.update"
    ):
        raise HTTPException(status_code=403, detail="RESOURCE_PERMISSION_DENIED")
    if resource.lifecycle is not ResourceLifecycle.ACTIVE:
        raise HTTPException(status_code=409, detail="RESOURCE_NOT_ACTIVE")

    task_type = "history.restore"
    input_ref = f"history.restore:v1:{resource_id}:{base_journal_seq}"
    repository = PostgresTaskRepository(session)
    existing = await repository.get_by_actor_idempotency_key(
        current.account_id, idempotency_key
    )
    if existing is not None and not _same_restore_task(
        existing, task_type, resource_id, input_ref
    ):
        raise HTTPException(status_code=409, detail="IDEMPOTENCY_KEY_CONFLICT")

    try:
        task = await CreateTask(repository).execute(
            task_type,
            input_ref=input_ref,
            actor_account_id=current.account_id,
            resource_id=resource_id,
            idempotency_key=idempotency_key,
        )
    except ConflictError as exc:
        raise HTTPException(status_code=409, detail=exc.error_code) from exc
    if not _same_restore_task(task, task_type, resource_id, input_ref):
        raise HTTPException(status_code=409, detail="IDEMPOTENCY_KEY_CONFLICT")
    return CreateVersionRestoreTaskResponse(
        taskId=task.task_id, task=_task_summary(task)
    )


def _same_restore_task(
    task: object, task_type: str, resource_id: UUID, input_ref: str
) -> bool:
    return (
        getattr(task, "task_type", None) == task_type
        and getattr(task, "resource_id", None) == resource_id
        and getattr(task, "input_ref", None) == input_ref
    )


@router.post("/resources/{resource_id}/versions", response_model=CreateVersionResponse)
async def create_named_version(
    resource_id: UUID,
    body: CreateVersionRequest,
    current: Annotated[Session, Depends(get_current_session)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> CreateVersionResponse:
    try:
        await PostgresResourceOwnershipRepository(session).authorize(
            current.account_id, resource_id, "resource.read"
        )
    except ResourcePermissionDeniedError:
        raise HTTPException(status_code=403, detail="RESOURCE_PERMISSION_DENIED")
    try:
        version = await CreateNamedVersion(PostgresHistoryRepository(session)).execute(
            resource_id,
            body.label,
            base_journal_seq=body.baseJournalSeq,
            created_by=current.account_id,
        )
    except NamedVersionLabelConflictError:
        raise HTTPException(status_code=409, detail="VERSION_LABEL_CONFLICT")
    except LookupError:
        raise HTTPException(status_code=404, detail="RESOURCE_NOT_FOUND")
    return CreateVersionResponse(
        resourceId=resource_id,
        versionId=version.version_id,
        label=version.label,
        baseJournalSeq=version.base_journal_seq,
    )
