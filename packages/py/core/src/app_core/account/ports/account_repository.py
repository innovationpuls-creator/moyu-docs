from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from app_core.account.domain.account import Account


@dataclass(frozen=True)
class AccountRecord:
    account: Account
    password_hash: str


class AccountRepositoryPort(Protocol):
    async def save(self, account: Account, password_hash: str) -> None: ...

    async def find_by_email(self, email: str) -> AccountRecord | None: ...

    async def find_by_account_id(self, account_id: UUID) -> AccountRecord | None: ...

    async def find_by_email_for_account(
        self, account_id: UUID
    ) -> AccountRecord | None: ...

    async def update(self, account: Account) -> None: ...

    async def update_password_hash(
        self, account_id: UUID, password_hash: str
    ) -> None: ...
