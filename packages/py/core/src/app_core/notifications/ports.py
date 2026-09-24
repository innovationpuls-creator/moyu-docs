from __future__ import annotations

from datetime import datetime
from typing import Protocol, Sequence
from uuid import UUID

from app_core.notifications.domain import Notification


class NotificationsRepository(Protocol):
    async def save(self, notification: Notification) -> Notification: ...
    async def list_for_account(
        self, account_id: UUID, *, limit: int = 50
    ) -> Sequence[Notification]: ...
    async def mark_read(
        self, notification_id: UUID, account_id: UUID, read_at: datetime
    ) -> bool: ...
    async def mark_all_read(self, account_id: UUID, read_at: datetime) -> int: ...


class AccountLookup(Protocol):
    async def find_id_by_email(self, email: str) -> UUID | None: ...
