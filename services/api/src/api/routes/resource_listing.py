from __future__ import annotations

from typing import Annotated
from uuid import UUID

from app_contracts.queries.resource.list_resources import (
    Item,
    Lifecycle,
    ListResourcesResponse,
    ResourceType,
)
from app_core.permission.domain.workspace_membership import WorkspaceOperation
from app_core.session.domain.session import Session
from app_infra.postgres.permission_workspace_repository import (
    PostgresWorkspaceMembershipRepository,
)
from app_infra.postgres.project_repository import PostgresProjectRepository
from app_infra.postgres.resource.resource_repository import (
    PostgresResourceRepository,
)
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from api.dependencies.auth import get_current_session, get_db_session

router = APIRouter()


@router.get("/projects/{project_id}/resources", response_model=ListResourcesResponse)
async def list_resources(
    project_id: UUID,
    current: Annotated[Session, Depends(get_current_session)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
    folder_id: Annotated[UUID | None, Query(alias="folderId")] = None,
) -> ListResourcesResponse:
    project = await PostgresProjectRepository(session).find_by_id(project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="RESOURCE_NOT_FOUND")
    # Authority: workspace membership READ (the project's workspace).
    try:
        await PostgresWorkspaceMembershipRepository(session).authorize(
            current.account_id,
            WorkspaceOperation.READ,
            workspace_id=project.workspace_id,
        )
    except Exception:
        raise HTTPException(status_code=403, detail="RESOURCE_PERMISSION_DENIED")
    rows = await PostgresResourceRepository(session).list_by_project(
        project_id, folder_id=folder_id
    )
    return ListResourcesResponse(
        projectId=project_id,
        items=[
            Item(
                resourceId=r.resource_id,
                folderId=r.folder_id,
                name=r.name,
                resourceType=ResourceType(r.resource_type),
                lifecycle=Lifecycle(r.lifecycle),
            )
            for r in rows
        ],
    )
