from __future__ import annotations

from datetime import datetime
from typing import Protocol
from uuid import UUID


class DeletionRepositoryPort(Protocol):
    async def schedule(self, account_id: UUID, execute_after: datetime) -> None: ...
    async def cancel(self, account_id: UUID, at: datetime) -> bool: ...
    async def complete(self, account_id: UUID, at: datetime) -> bool: ...
