from __future__ import annotations

from datetime import datetime
from uuid import UUID

from app_core.integrations import domain
from app_core.integrations.domain import IntegrationError, IntegrationKey
from app_core.integrations.ports import IntegrationKeyRepository


class IssueApiKey:
    """Arch 20 §11: issue an external key; the client's PRIVATE key is returned
    exactly once, only the public key is stored."""

    def __init__(self, keys: IntegrationKeyRepository) -> None:
        self._keys = keys

    async def execute(
        self, account_id: UUID, label: str
    ) -> tuple[IntegrationKey, bytes]:
        private, public_hex = domain.new_keypair()
        key = await self._keys.create(
            account_id=account_id,
            label=label,
            public_key_hex=public_hex,
        )
        return key, private


class RevokeApiKey:
    def __init__(self, keys: IntegrationKeyRepository) -> None:
        self._keys = keys

    async def execute(self, account_id: UUID, key_id: UUID) -> None:
        key = await self._keys.find_by_id(key_id)
        if key is None:
            raise LookupError("key not found")
        if key.account_id != account_id:
            raise IntegrationError("key not owned by actor")
        await self._keys.revoke(key_id)


class VerifySignedPayload:
    """Arch 20: replay-window Ed25519 verification with the stored public key."""

    def __init__(self, keys: IntegrationKeyRepository) -> None:
        self._keys = keys

    async def execute(
        self,
        key_id: UUID,
        payload: bytes,
        timestamp: datetime,
        signature: str,
    ) -> bool:
        key = await self._keys.find_by_id(key_id)
        public_hex = await self._keys.public_key_hex(key_id)
        if key is None or public_hex is None or key.revoked:
            return False
        return domain.verify(payload, timestamp, signature, public_hex)
