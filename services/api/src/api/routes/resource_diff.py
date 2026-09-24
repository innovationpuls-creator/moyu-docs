from __future__ import annotations

from typing import Annotated
from uuid import UUID

from app_core.history.diff import snapshot_diff
from app_core.resource.domain import ResourcePermissionDeniedError
from app_core.session.domain.session import Session
from app_infra.postgres.resource.checkpoint_repository import (
    PostgresCheckpointRepository,
)
from app_infra.postgres.resource_ownership_repository import (
    PostgresResourceOwnershipRepository,
)
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from api.dependencies.auth import get_current_session, get_db_session

router = APIRouter()


class DiffResponse(BaseModel):
    resourceId: UUID
    fromSeq: int | None
    toSeq: int | None
    diff: dict


@router.get("/resources/{resource_id}/diff", response_model=DiffResponse)
async def resource_diff(
    resource_id: UUID,
    current: Annotated[Session, Depends(get_current_session)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
    fromSeq: Annotated[int | None, Query()] = None,
    toSeq: Annotated[int | None, Query()] = None,
) -> DiffResponse:
    try:
        await PostgresResourceOwnershipRepository(session).authorize(
            current.account_id, resource_id, "resource.read"
        )
    except ResourcePermissionDeniedError:
        raise HTTPException(status_code=403, detail="RESOURCE_PERMISSION_DENIED")
    repo = PostgresCheckpointRepository(session)
    recent = await repo.list_recent(resource_id, limit=2)
    if not recent:
        return DiffResponse(resourceId=resource_id, fromSeq=None, toSeq=None, diff={})
    target = toSeq or recent[0].base_journal_seq
    after = next((c for c in recent if c.base_journal_seq == target), recent[0])
    before = recent[1] if len(recent) > 1 else None
    if fromSeq is not None:
        candidates = await repo.list_recent(resource_id, limit=50)
        before = next((c for c in candidates if c.base_journal_seq == fromSeq), before)
    return DiffResponse(
        resourceId=resource_id,
        fromSeq=before.base_journal_seq if before else None,
        toSeq=after.base_journal_seq,
        diff=snapshot_diff(before.snapshot if before else None, after.snapshot),
    )
