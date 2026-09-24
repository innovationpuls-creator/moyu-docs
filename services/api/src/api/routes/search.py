from __future__ import annotations

from datetime import datetime
from typing import Annotated
from uuid import UUID

from app_core.permission.domain.workspace_membership import WorkspaceOperation
from app_core.search.application import SearchWorkspace, SuggestSearches
from app_core.search.domain import SearchHit
from app_core.session.domain.session import Session
from app_infra.postgres.permission_workspace_repository import (
    PostgresWorkspaceMembershipRepository,
)
from app_infra.postgres.search_history_repository import (
    PostgresSearchHistoryRepository,
)
from app_infra.postgres.search_repository import PostgresSearchRepository
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from api.dependencies.auth import get_current_session, get_db_session

router = APIRouter()


class SearchItem(BaseModel):
    resourceId: UUID
    name: str
    resourceType: str
    score: float
    snippet: str | None = None


class SearchResponse(BaseModel):
    workspaceId: UUID
    query: str
    items: list[SearchItem]


@router.get("/workspaces/{workspace_id}/search", response_model=SearchResponse)
async def search_workspace(
    workspace_id: UUID,
    q: Annotated[str, Query(min_length=1, max_length=200)],
    current: Annotated[Session, Depends(get_current_session)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
    resourceType: Annotated[str | None, Query()] = None,
    since: Annotated[datetime | None, Query()] = None,
    until: Annotated[datetime | None, Query()] = None,
    author: Annotated[UUID | None, Query()] = None,
    projectId: Annotated[UUID | None, Query()] = None,
    folderId: Annotated[UUID | None, Query()] = None,
) -> SearchResponse:
    try:
        await PostgresWorkspaceMembershipRepository(session).authorize(
            current.account_id,
            WorkspaceOperation.READ,
            workspace_id=workspace_id,
        )
    except Exception:
        raise HTTPException(status_code=403, detail="WORKSPACE_PERMISSION_DENIED")
    await PostgresSearchHistoryRepository(session).record(current.account_id, q)
    hits: list[SearchHit] = await SearchWorkspace(
        PostgresSearchRepository(session)
    ).execute(
        workspace_id,
        q,
        resource_type=resourceType,
        since=since,
        until=until,
        author=author,
        project_id=projectId,
        folder_id=folderId,
    )
    return SearchResponse(
        workspaceId=workspace_id,
        query=q,
        items=[
            SearchItem(
                resourceId=h.resource_id,
                name=h.name,
                resourceType=h.resource_type,
                score=h.score,
                snippet=h.snippet,
            )
            for h in hits
        ],
    )


class HistoryItem(BaseModel):
    query: str
    lastUsedAt: str | None


class SearchHistoryResponse(BaseModel):
    items: list[HistoryItem]


@router.get("/search/history", response_model=SearchHistoryResponse)
async def search_history(
    current: Annotated[Session, Depends(get_current_session)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> SearchHistoryResponse:
    rows = await PostgresSearchHistoryRepository(session).list_for_account(
        current.account_id
    )
    return SearchHistoryResponse(
        items=[
            HistoryItem(
                query=query,
                lastUsedAt=created.isoformat() if created else None,
            )
            for query, created in rows
        ]
    )


class SuggestionsResponse(BaseModel):
    workspaceId: UUID
    prefix: str
    suggestions: list[str]


@router.get(
    "/workspaces/{workspace_id}/search/suggestions",
    response_model=SuggestionsResponse,
)
async def search_suggestions(
    workspace_id: UUID,
    q: Annotated[str, Query(min_length=1, max_length=200)],
    current: Annotated[Session, Depends(get_current_session)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> SuggestionsResponse:
    try:
        await PostgresWorkspaceMembershipRepository(session).authorize(
            current.account_id,
            WorkspaceOperation.READ,
            workspace_id=workspace_id,
        )
    except Exception:
        raise HTTPException(status_code=403, detail="WORKSPACE_PERMISSION_DENIED")
    suggestions = await SuggestSearches(PostgresSearchRepository(session)).execute(
        workspace_id, q
    )
    return SuggestionsResponse(
        workspaceId=workspace_id, prefix=q, suggestions=suggestions
    )


class CommentSearchItem(BaseModel):
    commentId: UUID
    resourceId: UUID
    resourceName: str
    body: str
    threadId: UUID


class CommentSearchResponse(BaseModel):
    workspaceId: UUID
    query: str
    items: list[CommentSearchItem]


@router.get(
    "/workspaces/{workspace_id}/search/comments",
    response_model=CommentSearchResponse,
)
async def search_comments(
    workspace_id: UUID,
    q: Annotated[str, Query(min_length=1, max_length=200)],
    current: Annotated[Session, Depends(get_current_session)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> CommentSearchResponse:
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
                __import__("sqlalchemy").text(
                    "SELECT c.comment_id, c.thread_id, c.resource_id, r.name, "
                    "c.body FROM collab.resource_comments c "
                    "JOIN core.resources r ON r.resource_id=c.resource_id "
                    "JOIN core.projects p ON p.project_id=r.project_id "
                    "WHERE p.workspace_id=:wid AND c.deleted=FALSE "
                    "AND (c.body ILIKE :pat) "
                    "ORDER BY c.created_at DESC LIMIT 25"
                ),
                {"wid": workspace_id, "pat": f"%{q}%"},
            )
        )
        .mappings()
        .all()
    )
    return CommentSearchResponse(
        workspaceId=workspace_id,
        query=q,
        items=[
            CommentSearchItem(
                commentId=row["comment_id"],
                threadId=row["thread_id"],
                resourceId=row["resource_id"],
                resourceName=str(row["name"]),
                body=str(row["body"]),
            )
            for row in rows
        ],
    )


class ClearHistoryResponse(BaseModel):
    cleared: int


@router.delete("/search/history", response_model=ClearHistoryResponse)
async def clear_search_history(
    current: Annotated[Session, Depends(get_current_session)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> ClearHistoryResponse:
    cleared = await PostgresSearchHistoryRepository(session).clear_for_account(
        current.account_id
    )
    return ClearHistoryResponse(cleared=cleared)
