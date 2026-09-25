from __future__ import annotations

from typing import Annotated, cast
from uuid import UUID

from app_contracts.commands.tasks.cancel_task import CancelTaskResponse
from app_contracts.commands.tasks.retry_task import RetryTaskResponse
from app_contracts.queries.tasks.get_task import GetTaskResponse
from app_contracts.queries.tasks.list_tasks import ListTasksResponse, TaskSummary
from app_core.operations.task import (
    CreateTask,
    GetTask,
    ListTasks,
    RequestCancel,
    RetryTask,
    TaskLike,
    TaskRepository,
)
from app_core.session.domain.session import Session
from app_infra.postgres.task.task_repository import PostgresTaskRepository
from fastapi import APIRouter, Depends, Header, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from api.dependencies.auth import get_current_session, get_db_session

router = APIRouter()


def get_task_repository(
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> TaskRepository:
    # The infrastructure repository is the single persistence adapter. Its
    # actor-scoped list query must implement the TaskRepository port.
    return cast(TaskRepository, PostgresTaskRepository(session))


def _task_summary(task: TaskLike) -> TaskSummary:
    state = getattr(task.state, "value", task.state)
    return TaskSummary.model_validate(
        {
            "taskId": task.task_id,
            "taskType": task.task_type,
            "state": state,
            "stage": task.stage,
            "messageCode": task.progress_message_code,
            "current": task.progress_current,
            "total": task.progress_total,
            "percentage": task.progress_percentage,
            "updatedAt": task.progress_updated_at,
            "retryCount": task.retry_count,
            "retryOfTaskId": task.retry_of_task_id,
            "cancelRequestedAt": task.cancel_requested_at,
            "queuedAt": task.queued_at,
            "startedAt": task.started_at,
            "finishedAt": task.finished_at,
            "failureCode": task.failure_code,
        }
    )


@router.get("/tasks", response_model=ListTasksResponse)
async def list_tasks(
    current: Annotated[Session, Depends(get_current_session)],
    repository: Annotated[TaskRepository, Depends(get_task_repository)],
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> ListTasksResponse:
    tasks = await ListTasks(repository).execute(
        current.account_id, limit=limit, offset=offset
    )
    return ListTasksResponse(
        tasks=[_task_summary(task) for task in tasks], limit=limit, offset=offset
    )


@router.get("/tasks/{task_id}", response_model=GetTaskResponse)
async def get_task(
    task_id: UUID,
    current: Annotated[Session, Depends(get_current_session)],
    repository: Annotated[TaskRepository, Depends(get_task_repository)],
) -> GetTaskResponse:
    task = await GetTask(repository).execute(task_id, current.account_id)
    return GetTaskResponse(task=_task_summary(task))


@router.post("/tasks/{task_id}/cancel", response_model=CancelTaskResponse)
async def cancel_task(
    task_id: UUID,
    current: Annotated[Session, Depends(get_current_session)],
    repository: Annotated[TaskRepository, Depends(get_task_repository)],
) -> CancelTaskResponse:
    task = await RequestCancel(repository).execute(task_id, current.account_id)
    return CancelTaskResponse(task=_task_summary(task))


@router.post(
    "/tasks/{task_id}/retry",
    response_model=RetryTaskResponse,
    status_code=status.HTTP_201_CREATED,
)
async def retry_task(
    task_id: UUID,
    idempotency_key: Annotated[UUID, Header(alias="Idempotency-Key")],
    current: Annotated[Session, Depends(get_current_session)],
    repository: Annotated[TaskRepository, Depends(get_task_repository)],
) -> RetryTaskResponse:
    create = CreateTask(repository)
    task = await RetryTask(repository, create).execute(
        task_id, current.account_id, idempotency_key
    )
    return RetryTaskResponse(task=_task_summary(task))
