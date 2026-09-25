from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated
from uuid import UUID

from app_contracts.commands.importexport.import_resource import (
    ImportResource as ImportResourceRequest,
)
from app_contracts.queries.importexport.export_resource import (
    Content,
    ExportResourceResponse,
)
from app_contracts.queries.importexport.export_resource import (
    Resource as ResourceMeta,
)
from app_contracts.queries.tasks.list_tasks import TaskSummary
from app_core.import_export.application import (
    CreateExportResourceTask,
    CreateImportResourceTask,
    GetExportResult,
)
from app_core.import_export.domain import (
    ImportExportConflictError,
    ImportExportExpiredError,
    ImportExportNotFoundError,
    ImportExportPayloadTooLargeError,
    ImportExportPermissionDeniedError,
)
from app_core.resource.application import ExportResource as ExportResourceUseCase
from app_core.resource.domain import ResourcePermissionDeniedError
from app_core.session.domain.session import Session
from app_infra.postgres.import_export_repository import (
    PostgresImportExportSessionRepository,
)
from app_infra.postgres.import_export_storage import (
    ImportExportTemporaryAssetStore,
    S3StoreError,
    TransactionReleasingTemporaryAssetStore,
    configured_asset_store,
)
from app_infra.postgres.project_repository import PostgresProjectRepository
from app_infra.postgres.resource.checkpoint_repository import (
    PostgresCheckpointRepository,
)
from app_infra.postgres.resource.resource_repository import (
    PostgresResourceRepository,
)
from app_infra.postgres.resource_ownership_repository import (
    PostgresResourceOwnershipRepository,
)
from app_infra.postgres.task.task_repository import PostgresTaskRepository
from fastapi import APIRouter, Depends, Header, HTTPException, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from api.dependencies.auth import get_current_session, get_db_session

router = APIRouter()


def _task_summary(task) -> TaskSummary:
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


@router.get("/resources/{resource_id}/export", response_model=ExportResourceResponse)
async def export_resource(
    resource_id: UUID,
    current: Annotated[Session, Depends(get_current_session)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> ExportResourceResponse:
    use_case = ExportResourceUseCase(
        PostgresResourceRepository(session),
        PostgresCheckpointRepository(session),
        PostgresResourceOwnershipRepository(session),
    )
    try:
        doc = await use_case.execute(current.account_id, resource_id)
    except ResourcePermissionDeniedError:
        raise HTTPException(status_code=403, detail="RESOURCE_PERMISSION_DENIED")
    except LookupError:
        raise HTTPException(status_code=404, detail="RESOURCE_NOT_FOUND")
    return ExportResourceResponse(
        kind=doc["kind"],
        schemaVersion=doc["schemaVersion"],
        exportedAt=datetime.now(UTC),
        resource=ResourceMeta(**doc["resource"]),
        content=Content(**doc["content"]),
    )


@router.post(
    "/resources/{resource_id}/import",
    status_code=status.HTTP_202_ACCEPTED,
)
async def import_resource(
    resource_id: UUID,
    body: ImportResourceRequest,
    current: Annotated[Session, Depends(get_current_session)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> dict:
    if body.resourceId != resource_id:
        raise HTTPException(status_code=400, detail="IMPORT_DOCUMENT_INVALID")
    ownership = PostgresResourceOwnershipRepository(session)
    sessions = PostgresImportExportSessionRepository(session)
    try:
        temporary_assets = TransactionReleasingTemporaryAssetStore(
            ImportExportTemporaryAssetStore(configured_asset_store()), session
        )
        use_case = CreateImportResourceTask(
            PostgresTaskRepository(session),
            sessions,
            temporary_assets,
            PostgresResourceRepository(session),
            PostgresProjectRepository(session),
            ownership,
        )
        task, _import_id = await use_case.execute(
            current.account_id,
            resource_id,
            body.document.model_dump(mode="json", by_alias=True),
            body.idempotencyKey,
        )
    except ImportExportPayloadTooLargeError:
        raise HTTPException(status_code=413, detail="IMPORT_PAYLOAD_TOO_LARGE")
    except ValueError:
        raise HTTPException(status_code=400, detail="IMPORT_DOCUMENT_INVALID")
    except ImportExportPermissionDeniedError:
        raise HTTPException(status_code=403, detail="RESOURCE_PERMISSION_DENIED")
    except ImportExportConflictError:
        raise HTTPException(status_code=409, detail="IDEMPOTENCY_KEY_CONFLICT")
    except (ImportExportExpiredError, ImportExportNotFoundError):
        raise HTTPException(status_code=404, detail="RESOURCE_NOT_FOUND")
    except (OSError, S3StoreError):
        raise HTTPException(status_code=503, detail="IMPORT_EXPORT_STORAGE_UNAVAILABLE")
    return {"taskId": task.task_id, "task": _task_summary(task)}


@router.post(
    "/resources/{resource_id}/export-tasks",
    status_code=status.HTTP_202_ACCEPTED,
)
async def create_resource_export_task(
    resource_id: UUID,
    idempotency_key: Annotated[UUID, Header(alias="Idempotency-Key")],
    current: Annotated[Session, Depends(get_current_session)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> dict:
    use_case = CreateExportResourceTask(
        PostgresTaskRepository(session),
        PostgresImportExportSessionRepository(session),
        PostgresResourceRepository(session),
        PostgresProjectRepository(session),
        PostgresResourceOwnershipRepository(session),
    )
    try:
        task, export_session_id = await use_case.execute(
            current.account_id, resource_id, idempotency_key
        )
    except ImportExportPermissionDeniedError:
        raise HTTPException(status_code=403, detail="RESOURCE_PERMISSION_DENIED")
    except ImportExportConflictError:
        raise HTTPException(status_code=409, detail="IDEMPOTENCY_KEY_CONFLICT")
    except ImportExportNotFoundError:
        raise HTTPException(status_code=404, detail="RESOURCE_NOT_FOUND")
    return {
        "taskId": task.task_id,
        "exportSessionId": export_session_id,
        "task": _task_summary(task),
    }


@router.get(
    "/resources/{resource_id}/exports/{export_session_id}/result",
    response_class=Response,
)
async def get_resource_export_result(
    resource_id: UUID,
    export_session_id: UUID,
    current: Annotated[Session, Depends(get_current_session)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> Response:
    try:
        use_case = GetExportResult(
            PostgresImportExportSessionRepository(session),
            TransactionReleasingTemporaryAssetStore(
                ImportExportTemporaryAssetStore(configured_asset_store()), session
            ),
            PostgresResourceRepository(session),
            PostgresResourceOwnershipRepository(session),
        )
        payload = await use_case.execute(
            current.account_id, resource_id, export_session_id
        )
    except ImportExportPermissionDeniedError:
        raise HTTPException(status_code=403, detail="RESOURCE_PERMISSION_DENIED")
    except (ImportExportExpiredError, ImportExportNotFoundError):
        raise HTTPException(status_code=404, detail="EXPORT_RESULT_NOT_FOUND")
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="EXPORT_RESULT_NOT_FOUND")
    except (OSError, S3StoreError):
        raise HTTPException(status_code=503, detail="IMPORT_EXPORT_STORAGE_UNAVAILABLE")
    return Response(
        content=payload,
        media_type="application/json",
        headers={"Content-Disposition": 'attachment; filename="resource-export.json"'},
    )
