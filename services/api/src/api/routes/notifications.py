from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated
from uuid import UUID

from app_core.session.domain.session import Session
from app_infra.postgres.notification_repository import (
    PostgresNotificationsRepository,
)
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from api.dependencies.auth import get_current_session, get_db_session

router = APIRouter()


class NotificationItem(BaseModel):
    notificationId: UUID
    kind: str
    targetRef: dict
    payload: dict
    createdAt: str | None
    readAt: str | None


class NotificationsResponse(BaseModel):
    items: list[NotificationItem]
    unreadCount: int


@router.get("/notifications", response_model=NotificationsResponse)
async def list_notifications(
    current: Annotated[Session, Depends(get_current_session)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> NotificationsResponse:
    repo = PostgresNotificationsRepository(session)
    rows = await repo.list_for_account(current.account_id)
    return NotificationsResponse(
        items=[
            NotificationItem(
                notificationId=n.notification_id,
                kind=n.kind,
                targetRef=n.target_ref or {},
                payload=n.payload,
                createdAt=n.created_at.isoformat() if n.created_at else None,
                readAt=n.read_at.isoformat() if n.read_at else None,
            )
            for n in rows
        ],
        unreadCount=await repo.unread_count(current.account_id),
    )


class MarkNotificationReadResponse(BaseModel):
    notificationId: UUID
    readAt: str


@router.post(
    "/notifications/{notification_id}/read",
    response_model=MarkNotificationReadResponse,
)
async def mark_notification_read(
    notification_id: UUID,
    current: Annotated[Session, Depends(get_current_session)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> MarkNotificationReadResponse:
    marked = await PostgresNotificationsRepository(session).mark_read(
        notification_id, current.account_id, datetime.now(UTC)
    )
    if not marked:
        raise HTTPException(status_code=404, detail="NOTIFICATION_NOT_FOUND")
    return MarkNotificationReadResponse(
        notificationId=notification_id, readAt=datetime.now(UTC).isoformat()
    )


class MarkReadResponse(BaseModel):
    marked: int


@router.post("/notifications/read-all", response_model=MarkReadResponse)
async def mark_all_read(
    current: Annotated[Session, Depends(get_current_session)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> MarkReadResponse:
    marked = await PostgresNotificationsRepository(session).mark_all_read(
        current.account_id, datetime.now(UTC)
    )
    return MarkReadResponse(marked=marked)
