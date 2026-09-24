from __future__ import annotations

from typing import Annotated
from uuid import UUID

from app_core.integrations.application import IssueApiKey, RevokeApiKey
from app_core.integrations.domain import IntegrationError
from app_core.session.domain.session import Session
from app_infra.postgres.integration_key_repository import (
    PostgresIntegrationKeyRepository,
)
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from api.dependencies.auth import get_current_session, get_db_session

router = APIRouter()


class IssueKeyRequest(BaseModel):
    label: str


class RotateKeyRequest(BaseModel):
    label: str


class IssueKeyResponse(BaseModel):
    keyId: UUID
    label: str
    privateKeyHex: str


@router.post("/integrations/api-keys", response_model=IssueKeyResponse)
async def issue_api_key(
    body: IssueKeyRequest,
    current: Annotated[Session, Depends(get_current_session)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> IssueKeyResponse:
    key, private = await IssueApiKey(PostgresIntegrationKeyRepository(session)).execute(
        current.account_id, body.label
    )
    return IssueKeyResponse(
        keyId=key.key_id,
        label=key.label,
        privateKeyHex=private.hex(),
    )


class RevokeKeyResponse(BaseModel):
    keyId: UUID
    revoked: bool = True


class RotateKeyResponse(BaseModel):
    keyId: UUID
    revokedKeyId: UUID
    label: str
    privateKeyHex: str


@router.post(
    "/integrations/api-keys/{key_id}/rotate",
    response_model=RotateKeyResponse,
)
async def rotate_api_key(
    key_id: UUID,
    body: RotateKeyRequest,
    current: Annotated[Session, Depends(get_current_session)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> RotateKeyResponse:
    repo = PostgresIntegrationKeyRepository(session)
    owner = await repo.find_by_id(key_id)
    if owner is None or owner.account_id != current.account_id:
        raise HTTPException(status_code=404, detail="INTEGRATION_KEY_NOT_FOUND")
    try:
        new_key, private = await IssueApiKey(repo).execute(
            current.account_id, body.label
        )
    except IntegrationError:
        raise HTTPException(status_code=400, detail="INTEGRATION_KEY_LIMIT_REACHED")
    await RevokeApiKey(repo).execute(current.account_id, key_id)
    return RotateKeyResponse(
        keyId=new_key.key_id,
        revokedKeyId=key_id,
        label=new_key.label,
        privateKeyHex=private.hex(),
    )


@router.post("/integrations/api-keys/{key_id}/revoke", response_model=RevokeKeyResponse)
async def revoke_api_key(
    key_id: UUID,
    current: Annotated[Session, Depends(get_current_session)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> RevokeKeyResponse:
    try:
        await RevokeApiKey(PostgresIntegrationKeyRepository(session)).execute(
            current.account_id, key_id
        )
    except IntegrationError:
        raise HTTPException(status_code=403, detail="INTEGRATION_KEY_DENIED")
    except LookupError:
        raise HTTPException(status_code=404, detail="INTEGRATION_KEY_NOT_FOUND")
    return RevokeKeyResponse(keyId=key_id)
