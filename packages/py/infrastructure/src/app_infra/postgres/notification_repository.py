from __future__ import annotations

import json
from datetime import datetime
from typing import Any
from uuid import UUID

from app_core.notifications.domain import Notification
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


class PostgresNotificationsRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def save(self, notification: Notification) -> Notification:
        result = await self._session.execute(
            text(
                "INSERT INTO collab.notifications "
                "(notification_id,recipient_account_id,type,target_ref,payload,"
                "source_event_id) "
                "VALUES (:nid,:aid,:kind,:target_ref,:payload,:source_event_id) "
                "ON CONFLICT (recipient_account_id,source_event_id,type) "
                "DO NOTHING RETURNING *"
            ),
            {
                "nid": notification.notification_id,
                "aid": notification.account_id,
                "kind": notification.kind,
                "target_ref": json.dumps(notification.target_ref or {}),
                "payload": json.dumps(notification.payload, default=str),
                "source_event_id": notification.source_event_id,
            },
        )
        row = result.mappings().one_or_none()
        if row is None:
            row = (
                (
                    await self._session.execute(
                        text(
                            "SELECT * FROM collab.notifications "
                            "WHERE recipient_account_id=:aid "
                            "AND source_event_id=:event_id "
                            "AND type=:kind"
                        ),
                        {
                            "aid": notification.account_id,
                            "event_id": notification.source_event_id,
                            "kind": notification.kind,
                        },
                    )
                )
                .mappings()
                .one()
            )
        return _to_notification(row)

    async def list_for_account(
        self, account_id: UUID, *, limit: int = 50
    ) -> list[Notification]:
        rows = (
            (
                await self._session.execute(
                    text(
                        "SELECT * FROM collab.notifications "
                        "WHERE recipient_account_id=:aid "
                        "ORDER BY created_at DESC LIMIT :lim"
                    ),
                    {"aid": account_id, "lim": limit},
                )
            )
            .mappings()
            .all()
        )
        return [_to_notification(r) for r in rows]

    async def mark_read(
        self, notification_id: UUID, account_id: UUID, read_at: datetime
    ) -> bool:
        result = await self._session.execute(
            text(
                "UPDATE collab.notifications SET read_at=:at "
                "WHERE notification_id=:nid AND recipient_account_id=:aid "
                "AND read_at IS NULL"
            ),
            {"at": read_at, "nid": notification_id, "aid": account_id},
        )
        rowcount = getattr(result, "rowcount", 0) or 0
        return rowcount > 0

    async def mark_all_read(self, account_id: UUID, read_at: datetime) -> int:
        result = await self._session.execute(
            text(
                "UPDATE collab.notifications SET read_at=:at "
                "WHERE recipient_account_id=:aid AND read_at IS NULL"
            ),
            {"at": read_at, "aid": account_id},
        )
        return getattr(result, "rowcount", 0) or 0

    async def unread_count(self, account_id: UUID) -> int:
        value = await self._session.scalar(
            text(
                "SELECT count(*) FROM collab.notifications "
                "WHERE recipient_account_id=:aid AND read_at IS NULL"
            ),
            {"aid": account_id},
        )
        return int(value or 0)


class PostgresAccountLookup:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def find_id_by_email(self, email: str) -> UUID | None:
        return await self._session.scalar(
            text(
                "SELECT account_id FROM auth.accounts "
                "WHERE normalized_email=:email LIMIT 1"
            ),
            {"email": email},
        )


def _to_notification(row: Any) -> Notification:
    return Notification(
        notification_id=row["notification_id"],
        account_id=row["recipient_account_id"],
        kind=row["type"],
        payload=dict(row["payload"]),
        created_at=row["created_at"],
        read_at=row["read_at"],
        target_ref=dict(row["target_ref"]),
        source_event_id=row["source_event_id"],
    )
