from __future__ import annotations

from typing import Annotated
from uuid import UUID

from app_core.ai.application import ApplyChangeSet, ProposeChangeSet
from app_core.ai.domain import ChangesetError
from app_core.session.domain.session import Session
from app_infra.ai.dev_changeset_provider import DevChangeProvider
from app_infra.postgres.changeset_repository import PostgresChangeSetRepository
from app_infra.postgres.resource.checkpoint_repository import (
    PostgresCheckpointRepository,
)
from app_infra.postgres.resource.journal_repository import PostgresJournalRepository
from app_infra.postgres.resource.resource_repository import PostgresResourceRepository
from app_infra.postgres.resource_ownership_repository import (
    PostgresResourceOwnershipRepository,
)
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from api.dependencies.auth import get_current_session, get_db_session

router = APIRouter()


class ProposeRequest(BaseModel):
    resourceId: UUID
    instruction: str


class ProposeResponse(BaseModel):
    changesetId: UUID
    status: str


@router.post("/ai/propose-changeset", response_model=ProposeResponse)
async def propose_changeset(
    body: ProposeRequest,
    current: Annotated[Session, Depends(get_current_session)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> ProposeResponse:
    use_case = ProposeChangeSet(
        PostgresChangeSetRepository(session),
        PostgresResourceRepository(session),
        DevChangeProvider(),
        PostgresResourceOwnershipRepository(session),
    )
    try:
        changeset = await use_case.execute(
            current.account_id, body.resourceId, instruction=body.instruction
        )
    except ChangesetError:
        raise HTTPException(status_code=403, detail="RESOURCE_PERMISSION_DENIED")
    except LookupError:
        raise HTTPException(status_code=404, detail="RESOURCE_NOT_FOUND")
    return ProposeResponse(
        changesetId=changeset.changeset_id, status=changeset.status.value
    )


class ApplyResponse(BaseModel):
    changesetId: UUID
    journalSeq: int
    status: str


@router.post("/changesets/{changeset_id}/apply", response_model=ApplyResponse)
async def apply_changeset(
    changeset_id: UUID,
    current: Annotated[Session, Depends(get_current_session)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> ApplyResponse:
    use_case = ApplyChangeSet(
        PostgresChangeSetRepository(session),
        PostgresResourceRepository(session),
        PostgresJournalRepository(session),
        PostgresCheckpointRepository(session),
        PostgresResourceOwnershipRepository(session),
    )
    try:
        seq = await use_case.execute(current.account_id, changeset_id)
    except ChangesetError:
        raise HTTPException(status_code=403, detail="RESOURCE_PERMISSION_DENIED")
    except LookupError:
        raise HTTPException(status_code=404, detail="CHANGESET_NOT_FOUND")
    return ApplyResponse(changesetId=changeset_id, journalSeq=seq, status="Applied")
