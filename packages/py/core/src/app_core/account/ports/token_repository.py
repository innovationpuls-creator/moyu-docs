from __future__ import annotations

from datetime import datetime
from typing import Protocol
from uuid import UUID

from app_core.account.domain.token import OneTimeToken, OneTimeTokenType


class TokenRepositoryPort(Protocol):
    async def save(self, token: OneTimeToken) -> None: ...

    async def invalidate_pending(
        self, account_id: UUID, token_type: OneTimeTokenType, at: datetime
    ) -> int: ...

    async def find_by_hash(self, token_hash: str) -> OneTimeToken | None: ...

    async def consume_by_secret(
        self, secret: str, at: datetime
    ) -> OneTimeToken | None: ...

    async def consume_password_reset_by_secret(
        self, secret: str, at: datetime
    ) -> OneTimeToken | None: ...

    async def consume_by_secret_for_account(
        self, secret: str, account_id: UUID, at: datetime
    ) -> OneTimeToken | None: ...

    async def count_recent(
        self, account_id: UUID, token_type: OneTimeTokenType, since: datetime
    ) -> int: ...
