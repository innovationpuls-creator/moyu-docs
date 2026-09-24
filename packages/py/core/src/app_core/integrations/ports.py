from __future__ import annotations

from typing import Protocol
from uuid import UUID

from app_core.integrations.domain import IntegrationKey


class IntegrationKeyRepository(Protocol):
    async def create(
        self,
        *,
        account_id: UUID,
        label: str,
        public_key_hex: str,
    ) -> IntegrationKey: ...
    async def find_by_id(self, key_id: UUID) -> IntegrationKey | None: ...
    async def public_key_hex(self, key_id: UUID) -> str | None: ...
    async def revoke(self, key_id: UUID) -> None: ...
