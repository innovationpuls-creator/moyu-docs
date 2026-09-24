from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated

from app_contracts.queries.workspace.list_workspaces import (
    Lifecycle as WorkspaceLifecycle,
)
from app_contracts.queries.workspace.list_workspaces import (
    ListWorkspacesResponse,
    MembershipKind,
    Workspace,
)
from app_core.session.domain.session import Session
from app_infra.postgres.permission_workspace_repository import (
    PostgresWorkspaceMembershipRepository,
)
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from api.dependencies.auth import get_current_session, get_db_session

router = APIRouter()


@router.get("/workspaces", response_model=ListWorkspacesResponse)
async def list_workspaces(
    current: Annotated[Session, Depends(get_current_session)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> ListWorkspacesResponse:
    membership = PostgresWorkspaceMembershipRepository(session)
    rows = await membership.list_workspaces_for_account(current.account_id)
    return ListWorkspacesResponse(
        workspaces=[
            Workspace(
                workspaceId=row[0],
                name=row[1],
                membershipKind=MembershipKind(row[2]),
                lifecycle=WorkspaceLifecycle(row[3]),
                createdAt=datetime.now(UTC),
            )
            for row in rows
        ]
    )
