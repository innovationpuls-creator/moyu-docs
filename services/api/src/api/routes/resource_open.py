from __future__ import annotations

from typing import Annotated
from uuid import UUID

from app_contracts.queries.resource.open_resource import (
    Lifecycle as ResourceLifecycle,
)
from app_contracts.queries.resource.open_resource import (
    OpenResourceResponse,
    ResourceType,
)
from app_core.session.domain.session import Session
from app_infra.nats.resource_content_gateway import ResourceContentGatewayError
from app_infra.postgres.resource.resource_repository import PostgresResourceRepository
from app_infra.postgres.resource_ownership_repository import (
    PostgresResourceOwnershipRepository,
)
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from api.dependencies.auth import get_current_session, get_db_session
from api.infra.broadcast import get_resource_content_gateway

router = APIRouter()


@router.get("/resources/{resource_id}", response_model=OpenResourceResponse)
async def open_resource(
    resource_id: UUID,
    current: Annotated[Session, Depends(get_current_session)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
    content: Annotated[object, Depends(get_resource_content_gateway)],
) -> OpenResourceResponse:
    resources = PostgresResourceRepository(session)
    resource = await resources.get(resource_id)
    if resource is None:
        raise HTTPException(status_code=404, detail="RESOURCE_NOT_FOUND")
    if resource.lifecycle in ("Trashed", "Purging", "Purged"):
        raise HTTPException(status_code=404, detail="RESOURCE_NOT_FOUND")
    ownership = PostgresResourceOwnershipRepository(session)
    ok = await ownership.authorize(current.account_id, resource_id, "resource.read")
    if not ok:
        raise HTTPException(status_code=403, detail="RESOURCE_PERMISSION_DENIED")
    try:
        current_content = await content.read(resource_id)
    except LookupError:
        raise HTTPException(status_code=404, detail="RESOURCE_NOT_FOUND")
    except ResourceContentGatewayError:
        raise HTTPException(status_code=503, detail="RESOURCE_CONTENT_UNAVAILABLE")
    return OpenResourceResponse(
        resourceId=resource.resource_id,
        projectId=resource.project_id,
        folderId=resource.folder_id,
        resourceType=ResourceType(resource.resource_type),
        name=resource.name,
        lifecycle=ResourceLifecycle(resource.lifecycle),
        journalSeq=current_content.journal_seq,
        snapshot=current_content.snapshot,
    )
