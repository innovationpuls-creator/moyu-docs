from __future__ import annotations

from base64 import b64decode
from datetime import UTC, datetime
from typing import Annotated
from uuid import UUID

from app_contracts.commands.resource.append_journal_op import (
    AppendJournalOp as AppendJournalOpRequest,
)
from app_contracts.commands.resource.append_journal_op import (
    AppendJournalOpResponse,
)
from app_contracts.commands.resource.create_resource import (
    CreateResource as CreateResourceRequest,
)
from app_contracts.commands.resource.create_resource import (
    CreateResourceResponse,
    ResourceType,
)
from app_contracts.commands.resource.create_resource import (
    Lifecycle as ResourceLifecycle,
)
from app_contracts.commands.resource.rename_resource import (
    RenameResource as RenameResourceRequest,
)
from app_contracts.commands.resource.rename_resource import (
    RenameResourceResponse,
)
from app_contracts.commands.resource.restore_resource import (
    Lifecycle as RestoreLifecycle,
)
from app_contracts.commands.resource.restore_resource import (
    RestoreResource as RestoreResourceRequest,
)
from app_contracts.commands.resource.restore_resource import (
    RestoreResourceResponse,
)
from app_contracts.commands.resource.trash_resource import (
    Lifecycle as TrashLifecycle,
)
from app_contracts.commands.resource.trash_resource import (
    TrashResource as TrashResourceRequest,
)
from app_contracts.commands.resource.trash_resource import (
    TrashResourceResponse,
)
from app_core.resource.application import AppendJournalOp as AppendJournalOpUseCase
from app_core.resource.application import CreateResource as CreateResourceUseCase
from app_core.resource.application import RenameResource as RenameResourceUseCase
from app_core.resource.application import RestoreResource as RestoreResourceUseCase
from app_core.resource.application import TrashResource as TrashResourceUseCase
from app_core.resource.domain import (
    InvalidResourceNameError,
    JournalSequenceConflictError,
    ResourceNameConflictError,
    ResourceNotFoundError,
    ResourcePermissionDeniedError,
)
from app_core.session.domain.session import Session
from app_infra.nats.resource_broadcast_publisher import (
    NatsResourceBroadcastPublisher,
)
from app_infra.postgres.audit.audit_repository import PostgresAuditRepository
from app_infra.postgres.resource.journal_repository import PostgresJournalRepository
from app_infra.postgres.resource.resource_repository import PostgresResourceRepository
from app_infra.postgres.resource_journal_idempotency_repository import (
    PostgresResourceJournalIdempotencyRepository,
)
from app_infra.postgres.resource_ownership_repository import (
    PostgresResourceOwnershipRepository,
)
from app_infra.postgres.webhook_enqueuer import (
    enqueue_webhook_events_for_resource,
)
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from api.dependencies.auth import get_current_session, get_db_session
from api.infra.broadcast import BroadcastRelayUnavailable, get_broadcast_publisher

router = APIRouter()


@router.post("/resources", response_model=CreateResourceResponse, status_code=201)
async def create_resource(
    body: CreateResourceRequest,
    current: Annotated[Session, Depends(get_current_session)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> CreateResourceResponse:
    use_case = CreateResourceUseCase(
        PostgresResourceRepository(session),
        PostgresResourceOwnershipRepository(session),
    )
    try:
        saved = await use_case.execute(
            current.account_id,
            project_id=body.projectId,
            folder_id=body.folderId,
            resource_type=body.resourceType.value,
            name=body.name,
        )
    except ResourceNameConflictError:
        raise HTTPException(status_code=409, detail="RESOURCE_NAME_CONFLICT")
    except ResourcePermissionDeniedError:
        raise HTTPException(status_code=403, detail="RESOURCE_PERMISSION_DENIED")
    except ResourceNotFoundError:
        raise HTTPException(status_code=404, detail="RESOURCE_NOT_FOUND")
    except InvalidResourceNameError:
        raise HTTPException(status_code=400, detail="RESOURCE_NAME_INVALID")
    # The creator (workspace-Owner) becomes the resource's owner row (Permission-
    # owned grant; the Resource module never writes ownership itself).
    await PostgresResourceOwnershipRepository(session).grant(
        saved.resource_id, current.account_id
    )
    # Webhooks (arch 10): resource.created delivery is best-effort.
    try:
        await enqueue_webhook_events_for_resource(
            session, saved.resource_id, "resource.created"
        )
    except Exception:
        __import__("logging").getLogger("dom.api.resources").warning(
            "webhook enqueue skipped for resource"
        )
    return CreateResourceResponse(
        resourceId=saved.resource_id,
        projectId=saved.project_id,
        folderId=saved.folder_id,
        resourceType=ResourceType(saved.resource_type),
        name=saved.name,
        lifecycle=ResourceLifecycle(saved.lifecycle),
        createdAt=datetime.now(UTC),
    )


@router.post("/resources/{resource_id}/journal", response_model=AppendJournalOpResponse)
async def append_journal_op(
    resource_id: UUID,
    body: AppendJournalOpRequest,
    current: Annotated[Session, Depends(get_current_session)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
    publisher: Annotated[
        NatsResourceBroadcastPublisher, Depends(get_broadcast_publisher)
    ],
) -> AppendJournalOpResponse:
    if body.resourceId != resource_id:
        raise HTTPException(status_code=400, detail="RESOURCE_ID_MISMATCH")
    journal = PostgresJournalRepository(session)
    use_case = AppendJournalOpUseCase(
        PostgresResourceRepository(session),
        journal,
        PostgresResourceOwnershipRepository(session),
        idempotency=PostgresResourceJournalIdempotencyRepository(session),
    )
    update = b64decode(body.update)
    try:
        op = await use_case.execute(
            current.account_id,
            resource_id,
            update,
            ownership_epoch=1,
            expected_seq=body.expectedSeq,
            idempotency_key=str(body.idempotencyKey),
        )
    except ResourcePermissionDeniedError:
        raise HTTPException(status_code=403, detail="RESOURCE_PERMISSION_DENIED")
    except JournalSequenceConflictError:
        raise HTTPException(
            status_code=409, detail="RESOURCE_JOURNAL_SEQUENCE_CONFLICT"
        )
    except LookupError:
        raise HTTPException(status_code=404, detail="RESOURCE_NOT_FOUND")
    if op.durable_at is None:
        raise HTTPException(status_code=503, detail="JOURNAL_DURABILITY_UNCONFIRMED")
    # The durable receipt is issued only after PostgreSQL confirms commit. A
    # retry after a lost HTTP response replays the idempotent journal receipt.
    await session.commit()
    # Realtime: relay the op to collaborating clients (rt.broadcast.<id>).
    try:
        await publisher.publish(
            op.resource_id,
            "op",
            {
                "journalSeq": op.journal_seq,
                "updateSha256": op.update_hash,
            },
            sequence=op.journal_seq,
        )
    except BroadcastRelayUnavailable:
        raise HTTPException(status_code=503, detail="RELAY_UNAVAILABLE")
    return AppendJournalOpResponse(
        resourceId=op.resource_id,
        journalSeq=op.journal_seq,
        updateSha256=op.update_hash,
        acceptedWatermark=op.journal_seq,
        durableWatermark=op.journal_seq,
    )


@router.patch("/resources/{resource_id}", response_model=RenameResourceResponse)
async def rename_resource(
    resource_id: UUID,
    body: RenameResourceRequest,
    current: Annotated[Session, Depends(get_current_session)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> RenameResourceResponse:
    use_case = RenameResourceUseCase(
        PostgresResourceRepository(session),
        PostgresResourceOwnershipRepository(session),
    )
    try:
        saved = await use_case.execute(current.account_id, resource_id, name=body.name)
    except ResourcePermissionDeniedError:
        raise HTTPException(status_code=403, detail="RESOURCE_PERMISSION_DENIED")
    except ResourceNameConflictError:
        raise HTTPException(status_code=409, detail="RESOURCE_NAME_CONFLICT")
    except LookupError:
        raise HTTPException(status_code=404, detail="RESOURCE_NOT_FOUND")
    return RenameResourceResponse(
        resourceId=saved.resource_id,
        name=saved.name,
    )


@router.post("/resources/{resource_id}/trash", response_model=TrashResourceResponse)
async def trash_resource(
    resource_id: UUID,
    body: TrashResourceRequest,
    current: Annotated[Session, Depends(get_current_session)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> TrashResourceResponse:
    use_case = TrashResourceUseCase(
        PostgresResourceRepository(session),
        PostgresResourceOwnershipRepository(session),
    )
    try:
        saved = await use_case.execute(current.account_id, resource_id)
    except ResourcePermissionDeniedError:
        raise HTTPException(status_code=403, detail="RESOURCE_PERMISSION_DENIED")
    except LookupError:
        raise HTTPException(status_code=404, detail="RESOURCE_NOT_FOUND")
    await PostgresAuditRepository(session).record(
        actor_account_id=current.account_id,
        action="resource.trashed",
        target_type="resource",
        target_id=saved.resource_id,
    )
    return TrashResourceResponse(
        resourceId=saved.resource_id,
        lifecycle=TrashLifecycle(saved.lifecycle),
    )


@router.post("/resources/{resource_id}/restore", response_model=RestoreResourceResponse)
async def restore_resource(
    resource_id: UUID,
    body: RestoreResourceRequest,
    current: Annotated[Session, Depends(get_current_session)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> RestoreResourceResponse:
    use_case = RestoreResourceUseCase(
        PostgresResourceRepository(session),
        PostgresResourceOwnershipRepository(session),
    )
    try:
        saved = await use_case.execute(current.account_id, resource_id)
    except ResourcePermissionDeniedError:
        raise HTTPException(status_code=403, detail="RESOURCE_PERMISSION_DENIED")
    except LookupError:
        raise HTTPException(status_code=404, detail="RESOURCE_NOT_FOUND")
    await PostgresAuditRepository(session).record(
        actor_account_id=current.account_id,
        action="resource.restored",
        target_type="resource",
        target_id=saved.resource_id,
    )
    return RestoreResourceResponse(
        resourceId=saved.resource_id,
        lifecycle=RestoreLifecycle(saved.lifecycle),
    )
