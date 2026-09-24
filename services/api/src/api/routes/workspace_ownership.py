from __future__ import annotations

from app_contracts.queries.permission.has_sole_workspace_ownership import (
    HasSoleWorkspaceOwnershipResponse,
)
from app_core.session.domain.session import Session
from fastapi import APIRouter, Depends

from api.dependencies.auth import get_current_session
from api.dependencies.workspace_ownership import (
    PostgresWorkspaceOwnershipQuery,
    get_workspace_ownership,
)

router = APIRouter()


@router.get(
    "/my-workspace-ownership",
    response_model=HasSoleWorkspaceOwnershipResponse,
)
async def my_workspace_ownership(
    current: Session = Depends(get_current_session),
    ownership: PostgresWorkspaceOwnershipQuery = Depends(get_workspace_ownership),
) -> HasSoleWorkspaceOwnershipResponse:
    is_sole, _, workspace_id = await ownership.sole_owned_workspace(current.account_id)
    return HasSoleWorkspaceOwnershipResponse(
        hasSoleWorkspaceOwnership=is_sole,
        workspaceId=workspace_id if is_sole else None,
    )
