from __future__ import annotations

from typing import Annotated
from uuid import UUID

from app_core.permission.domain.workspace_membership import WorkspaceOperation
from app_core.session.domain.session import Session
from app_infra.postgres.permission_workspace_repository import (
    PostgresWorkspaceMembershipRepository,
)
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from api.dependencies.auth import get_current_session, get_db_session

router = APIRouter()


class MemberSuggestion(BaseModel):
    accountId: UUID
    email: str


class MemberSuggestionsResponse(BaseModel):
    workspaceId: UUID
    suggestions: list[MemberSuggestion]


@router.get(
    "/workspaces/{workspace_id}/members/suggest",
    response_model=MemberSuggestionsResponse,
)
async def suggest_members(
    workspace_id: UUID,
    q: Annotated[str, Query(min_length=1, max_length=200)],
    current: Annotated[Session, Depends(get_current_session)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> MemberSuggestionsResponse:
    try:
        await PostgresWorkspaceMembershipRepository(session).authorize(
            current.account_id,
            WorkspaceOperation.READ,
            workspace_id=workspace_id,
        )
    except Exception:
        raise HTTPException(status_code=403, detail="WORKSPACE_PERMISSION_DENIED")
    rows = (
        (
            await session.execute(
                text(
                    "SELECT a.account_id, a.primary_email FROM auth.accounts a "
                    "JOIN core.workspace_members wm "
                    "ON wm.account_id=a.account_id "
                    "WHERE wm.workspace_id=:wid AND a.primary_email ILIKE :pat "
                    "ORDER BY a.primary_email LIMIT 8"
                ),
                {"wid": workspace_id, "pat": f"%{q}%"},
            )
        )
        .mappings()
        .all()
    )
    return MemberSuggestionsResponse(
        workspaceId=workspace_id,
        suggestions=[
            MemberSuggestion(
                accountId=row["account_id"], email=str(row["primary_email"])
            )
            for row in rows
        ],
    )
