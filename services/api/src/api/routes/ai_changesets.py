from __future__ import annotations

from typing import Annotated
from uuid import UUID

from app_contracts.commands.ai.apply_changeset import (
    ApplyChangeSetResponse,
)
from app_contracts.commands.ai.apply_changeset import (
    Status as ApplyChangeSetStatus,
)
from app_contracts.commands.ai.propose_changeset import (
    ProposeChangeSet as ProposeChangeSetRequest,
)
from app_contracts.commands.ai.propose_changeset import (
    ProposeChangeSetResponse,
)
from app_contracts.commands.ai.propose_changeset import (
    Status as ProposeChangeSetStatus,
)
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
from sqlalchemy.ext.asyncio import AsyncSession

from api.dependencies.auth import get_current_session, get_db_session

router = APIRouter()


@router.post("/ai/propose-changeset", response_model=ProposeChangeSetResponse)
async def propose_changeset(
    body: ProposeChangeSetRequest,
    current: Annotated[Session, Depends(get_current_session)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> ProposeChangeSetResponse:
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
    return ProposeChangeSetResponse(
        changesetId=changeset.changeset_id,
        resourceId=changeset.resource_id,
        instruction=changeset.instruction,
        operations=changeset.ops,
        status=ProposeChangeSetStatus.Proposed,
    )


@router.post("/changesets/{changeset_id}/apply", response_model=ApplyChangeSetResponse)
async def apply_changeset(
    changeset_id: UUID,
    current: Annotated[Session, Depends(get_current_session)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> ApplyChangeSetResponse:
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
    return ApplyChangeSetResponse(
        changesetId=changeset_id,
        journalSeq=seq,
        status=ApplyChangeSetStatus.Applied,
    )
