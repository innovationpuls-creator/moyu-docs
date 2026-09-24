"""Public API (arch 22): machine clients authenticate with an integration key
(Ed25519 signature over the request body + replay window) instead of a session.
Only the parts the key owner may read are exposed; keep the surface minimal.
"""

from __future__ import annotations

import os
from datetime import UTC, datetime
from typing import Annotated, Any
from uuid import UUID

from app_core.integrations.application import VerifySignedPayload
from app_infra.postgres.integration_key_repository import (
    PostgresIntegrationKeyRepository,
)
from app_infra.postgres.notification_repository import PostgresNotificationsRepository
from app_infra.postgres.resource.resource_repository import PostgresResourceRepository
from app_infra.valkey.public_rate_limiter import (
    PublicApiRateLimiter,
    PublicRateLimitExceeded,
)
from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from api.dependencies.auth import get_db_session, get_valkey

router = APIRouter()


def get_public_rate_limiter(
    valkey: Annotated[Any, Depends(get_valkey)],
) -> PublicApiRateLimiter:
    limit = int(os.environ.get("PUBLIC_RATE_LIMIT", "120"))
    return PublicApiRateLimiter(valkey, limit=limit)


NO_ACTOR = UUID(int=0)


async def _resolve_actor(
    session: AsyncSession,
    x_dom_key_id: str | None,
    x_dom_signature: str | None,
    x_dom_timestamp: str | None,
    body: bytes,
) -> UUID:
    if not (x_dom_key_id and x_dom_signature and x_dom_timestamp):
        raise HTTPException(status_code=401, detail="INTEGRATION_AUTH_REQUIRED")
    try:
        key_id = UUID(x_dom_key_id)
        timestamp = datetime.fromtimestamp(int(x_dom_timestamp), UTC)
    except (ValueError, TypeError):
        raise HTTPException(status_code=401, detail="INTEGRATION_AUTH_REQUIRED")
    valid = await VerifySignedPayload(
        PostgresIntegrationKeyRepository(session)
    ).execute(key_id, body, timestamp, x_dom_signature)
    if not valid:
        raise HTTPException(status_code=401, detail="INTEGRATION_AUTH_UNAUTHORIZED")
    key = await PostgresIntegrationKeyRepository(session).find_by_id(key_id)
    if key is None:
        raise HTTPException(status_code=401, detail="INTEGRATION_AUTH_UNAUTHORIZED")
    return key.account_id


class PublicNotificationItem(BaseModel):
    notificationId: UUID
    kind: str
    payload: dict
    readAt: str | None


class PublicNotificationsResponse(BaseModel):
    items: list[PublicNotificationItem]


@router.get("/public/notifications", response_model=PublicNotificationsResponse)
async def public_list_notifications(
    rate_limiter: Annotated[PublicApiRateLimiter, Depends(get_public_rate_limiter)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
    x_dom_key_id: Annotated[str | None, Header()] = None,
    x_dom_signature: Annotated[str | None, Header()] = None,
    x_dom_timestamp: Annotated[str | None, Header()] = None,
) -> PublicNotificationsResponse:
    body: bytes = b""
    actor = await _resolve_actor(
        session, x_dom_key_id, x_dom_signature, x_dom_timestamp, body
    )
    try:
        await rate_limiter.check_and_record(str(actor), "notifications")
    except PublicRateLimitExceeded:
        raise HTTPException(status_code=429, detail="RATE_LIMITED")
    rows = await PostgresNotificationsRepository(session).list_for_account(actor)
    return PublicNotificationsResponse(
        items=[
            PublicNotificationItem(
                notificationId=n.notification_id,
                kind=n.kind,
                payload=dict(n.payload or {}),
                readAt=n.read_at.isoformat() if n.read_at else None,
            )
            for n in rows
        ]
    )


class PublicResourceItem(BaseModel):
    resourceId: UUID
    resourceType: str
    name: str
    updatedAt: str | None


class PublicResourcesResponse(BaseModel):
    items: list[PublicResourceItem]


@router.get("/public/resources", response_model=PublicResourcesResponse)
async def public_list_resources(
    rate_limiter: Annotated[PublicApiRateLimiter, Depends(get_public_rate_limiter)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
    x_dom_key_id: Annotated[str | None, Header()] = None,
    x_dom_signature: Annotated[str | None, Header()] = None,
    x_dom_timestamp: Annotated[str | None, Header()] = None,
) -> PublicResourcesResponse:
    actor = await _resolve_actor(
        session, x_dom_key_id, x_dom_signature, x_dom_timestamp, b""
    )
    try:
        await rate_limiter.check_and_record(str(actor), "resources")
    except PublicRateLimitExceeded:
        raise HTTPException(status_code=429, detail="RATE_LIMITED")
    rows = await PostgresResourceRepository(session).list_readable_for_account(actor)
    return PublicResourcesResponse(
        items=[
            PublicResourceItem(
                resourceId=r.resource_id,
                resourceType=r.resource_type,
                name=r.name,
                updatedAt=r.updated_at.isoformat() if r.updated_at else None,
            )
            for r in rows
        ]
    )
