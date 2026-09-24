from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated
from uuid import UUID

from app_contracts.commands.importexport.import_resource import (
    ImportResource as ImportResourceRequest,
)
from app_contracts.commands.importexport.import_resource import (
    ImportResourceResponse,
)
from app_contracts.queries.importexport.export_resource import (
    Content,
    ExportResourceResponse,
)
from app_contracts.queries.importexport.export_resource import (
    Resource as ResourceMeta,
)
from app_core.resource.application import ExportResource as ExportResourceUseCase
from app_core.resource.application import ImportResource as ImportResourceUseCase
from app_core.resource.domain import ResourcePermissionDeniedError
from app_core.session.domain.session import Session
from app_infra.postgres.resource.checkpoint_repository import (
    PostgresCheckpointRepository,
)
from app_infra.postgres.resource.journal_repository import PostgresJournalRepository
from app_infra.postgres.resource.resource_repository import (
    PostgresResourceRepository,
)
from app_infra.postgres.resource_ownership_repository import (
    PostgresResourceOwnershipRepository,
)
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from api.dependencies.auth import get_current_session, get_db_session

router = APIRouter()


@router.get("/resources/{resource_id}/export", response_model=ExportResourceResponse)
async def export_resource(
    resource_id: UUID,
    current: Annotated[Session, Depends(get_current_session)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> ExportResourceResponse:
    use_case = ExportResourceUseCase(
        PostgresResourceRepository(session),
        PostgresCheckpointRepository(session),
        PostgresResourceOwnershipRepository(session),
    )
    try:
        doc = await use_case.execute(current.account_id, resource_id)
    except ResourcePermissionDeniedError:
        raise HTTPException(status_code=403, detail="RESOURCE_PERMISSION_DENIED")
    except LookupError:
        raise HTTPException(status_code=404, detail="RESOURCE_NOT_FOUND")
    return ExportResourceResponse(
        kind=doc["kind"],
        schemaVersion=doc["schemaVersion"],
        exportedAt=datetime.now(UTC),
        resource=ResourceMeta(**doc["resource"]),
        content=Content(**doc["content"]),
    )


@router.post(
    "/resources/{resource_id}/import",
    response_model=ImportResourceResponse,
)
async def import_resource(
    resource_id: UUID,
    body: ImportResourceRequest,
    current: Annotated[Session, Depends(get_current_session)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> ImportResourceResponse:
    use_case = ImportResourceUseCase(
        PostgresResourceRepository(session),
        PostgresJournalRepository(session),
        PostgresCheckpointRepository(session),
        PostgresResourceOwnershipRepository(session),
    )
    try:
        seq, _checkpoint = await use_case.execute(
            current.account_id,
            resource_id,
            dict(body.document) if body.document else {},
        )
    except ValueError:
        raise HTTPException(status_code=400, detail="IMPORT_DOCUMENT_INVALID")
    except ResourcePermissionDeniedError:
        raise HTTPException(status_code=403, detail="RESOURCE_PERMISSION_DENIED")
    except LookupError:
        raise HTTPException(status_code=404, detail="RESOURCE_NOT_FOUND")
    return ImportResourceResponse(resourceId=resource_id, journalSeq=seq)
