from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated
from uuid import UUID

from app_contracts.queries.workspace.list_projects import (
    Lifecycle as ProjectLifecycle,
)
from app_contracts.queries.workspace.list_projects import (
    ListProjectsResponse,
    ProjectSummary,
)
from app_core.permission.domain.workspace_membership import WorkspaceOperation
from app_core.session.domain.session import Session
from app_infra.postgres.permission_workspace_repository import (
    PostgresWorkspaceMembershipRepository,
)
from app_infra.postgres.project_repository import PostgresProjectRepository
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from api.dependencies.auth import get_current_session, get_db_session

router = APIRouter()


@router.get("/workspaces/{workspace_id}/projects", response_model=ListProjectsResponse)
async def list_projects(
    workspace_id: UUID,
    current: Annotated[Session, Depends(get_current_session)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> ListProjectsResponse:
    # Authority: workspace membership (Permission-owned); READ suffices.
    try:
        await PostgresWorkspaceMembershipRepository(session).authorize(
            current.account_id,
            WorkspaceOperation.READ,
            workspace_id=workspace_id,
        )
    except Exception:
        raise HTTPException(status_code=403, detail="WORKSPACE_PERMISSION_DENIED")
    projects = await PostgresProjectRepository(session).list_by_workspace(workspace_id)
    return ListProjectsResponse(
        workspaceId=workspace_id,
        items=[
            ProjectSummary(
                projectId=p.project_id,
                workspaceId=workspace_id,
                name=p.name.display,
                lifecycle=ProjectLifecycle(p.lifecycle.value),
                updatedAt=p.updated_at or datetime.now(UTC),
            )
            for p in projects
        ],
        nextCursor=None,
    )
