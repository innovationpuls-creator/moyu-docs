from __future__ import annotations

import json
import secrets
import uuid
from datetime import datetime, timezone
from typing import Annotated, Any

import httpx
from app_core.integrations.domain import sign
from app_core.permission.domain.workspace_membership import WorkspaceOperation
from app_core.session.domain.session import Session
from app_infra.postgres.permission_workspace_repository import (
    PostgresWorkspaceMembershipRepository,
)
from app_infra.postgres.webhook_repository import PostgresWebhookSubscriptionRepository
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, HttpUrl
from sqlalchemy.ext.asyncio import AsyncSession

from api.dependencies.auth import get_current_session, get_db_session

router = APIRouter()


class RegisterWebhookRequest(BaseModel):
    url: HttpUrl = Field(..., max_length=2000)


class WebhookItem(BaseModel):
    subscriptionId: uuid.UUID
    url: str
    status: str
    createdAt: str | None


class RegisterWebhookResponse(BaseModel):
    subscriptionId: uuid.UUID


class ListWebhooksResponse(BaseModel):
    workspaceId: uuid.UUID
    items: list[WebhookItem]


class RemoveWebhookResponse(BaseModel):
    removed: bool


class TestWebhookResponse(BaseModel):
    delivered: bool
    statusCode: int


def get_webhook_transport() -> httpx.AsyncBaseTransport | None:
    """Transport hook for tests (MockTransport); defaults to the real network."""


async def _authorize_write(
    session: AsyncSession, account_id: uuid.UUID, workspace_id: uuid.UUID
) -> None:
    try:
        await PostgresWorkspaceMembershipRepository(session).authorize(
            account_id,
            WorkspaceOperation.MANAGE,
            workspace_id=workspace_id,
        )
    except Exception:
        raise HTTPException(status_code=403, detail="WORKSPACE_PERMISSION_DENIED")


@router.post(
    "/workspaces/{workspace_id}/webhooks",
    response_model=RegisterWebhookResponse,
)
async def register_webhook(
    workspace_id: uuid.UUID,
    body: RegisterWebhookRequest,
    current: Annotated[Session, Depends(get_current_session)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> RegisterWebhookResponse:
    await _authorize_write(session, current.account_id, workspace_id)
    repo = PostgresWebhookSubscriptionRepository(session)
    subscription_id = await repo.register(
        workspace_id, current.account_id, str(body.url), secrets.token_hex(32)
    )
    return RegisterWebhookResponse(subscriptionId=subscription_id)


@router.get(
    "/workspaces/{workspace_id}/webhooks",
    response_model=ListWebhooksResponse,
)
async def list_webhooks(
    workspace_id: uuid.UUID,
    current: Annotated[Session, Depends(get_current_session)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> ListWebhooksResponse:
    await _authorize_write(session, current.account_id, workspace_id)
    rows = await PostgresWebhookSubscriptionRepository(session).list_for_workspace(
        workspace_id
    )
    return ListWebhooksResponse(
        workspaceId=workspace_id,
        items=[
            WebhookItem(
                subscriptionId=row["subscription_id"],
                url=str(row["url"]),
                status=str(row["status"]),
                createdAt=(
                    row["created_at"].isoformat() if row["created_at"] else None
                ),
            )
            for row in rows
        ],
    )


@router.delete(
    "/workspaces/{workspace_id}/webhooks/{subscription_id}",
    response_model=RemoveWebhookResponse,
)
async def remove_webhook(
    workspace_id: uuid.UUID,
    subscription_id: uuid.UUID,
    current: Annotated[Session, Depends(get_current_session)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> RemoveWebhookResponse:
    await _authorize_write(session, current.account_id, workspace_id)
    removed = await PostgresWebhookSubscriptionRepository(session).remove(
        subscription_id, workspace_id
    )
    if not removed:
        raise HTTPException(status_code=404, detail="WEBHOOK_SUBSCRIPTION_NOT_FOUND")
    return RemoveWebhookResponse(removed=True)


class RequeueResponse(BaseModel):
    requeued: int
    remainingFailed: int


@router.post(
    "/webhooks/{webhook_id}/deliveries/requeue",
    response_model=RequeueResponse,
)
async def requeue_webhook_deliveries(
    webhook_id: uuid.UUID,
    current: Annotated[Session, Depends(get_current_session)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> RequeueResponse:
    """Arch 10: replay the newest Failed delivery as a fresh Queued task."""
    from app_core.webhook.application import RequeueWebhookDeliveries
    from app_infra.postgres.webhook_dead_letters import PostgresWebhookDeadLetters

    fetched = await PostgresWebhookSubscriptionRepository(session).fetch_by_id(
        webhook_id
    )
    if fetched is None:
        raise HTTPException(status_code=404, detail="WEBHOOK_SUBSCRIPTION_NOT_FOUND")
    workspace_id, _url, _secret = fetched
    await _authorize_write(session, current.account_id, workspace_id)
    result = await RequeueWebhookDeliveries(
        PostgresWebhookDeadLetters(session)
    ).execute(webhook_id)
    return RequeueResponse(
        requeued=result.requeued, remainingFailed=result.remainingFailed
    )


@router.post(
    "/workspaces/{workspace_id}/webhooks/{subscription_id}/test",
    response_model=TestWebhookResponse,
)
async def test_webhook(
    workspace_id: uuid.UUID,
    subscription_id: uuid.UUID,
    current: Annotated[Session, Depends(get_current_session)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
    transport: Annotated[
        httpx.AsyncBaseTransport | None, Depends(get_webhook_transport)
    ],
) -> TestWebhookResponse:
    await _authorize_write(session, current.account_id, workspace_id)
    fetched = await PostgresWebhookSubscriptionRepository(session).fetch(
        workspace_id, subscription_id
    )
    if fetched is None:
        raise HTTPException(status_code=404, detail="WEBHOOK_SUBSCRIPTION_NOT_FOUND")
    url, secret_key_hex = fetched
    private_key = bytes.fromhex(secret_key_hex)
    now = datetime.now(timezone.utc)
    payload = json.dumps(
        {
            "event": "webhook.test",
            "workspaceId": str(workspace_id),
            "deliveredAt": now.isoformat(),
        },
        separators=(",", ":"),
    ).encode()
    client_options: dict[str, Any] = {"timeout": 10.0}
    if transport is not None:
        client_options["transport"] = transport
    async with httpx.AsyncClient(**client_options) as client:
        try:
            response = await client.post(
                url,
                content=payload,
                headers={
                    "X-Dom-Signature": sign(payload, now, private_key),
                    "X-Dom-Timestamp": str(int(now.timestamp())),
                    "Content-Type": "application/json",
                },
            )
            return TestWebhookResponse(
                delivered=response.status_code < 400,
                statusCode=response.status_code,
            )
        except httpx.HTTPError:
            return TestWebhookResponse(delivered=False, statusCode=0)
