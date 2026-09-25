from __future__ import annotations

import hashlib
import secrets
from datetime import UTC, datetime
from urllib.parse import quote
from uuid import UUID

from app_core.common.exceptions import ValidationError
from app_core.permission.domain.share_link import (
    AnonymousShareGrant,
    CreatedShareLink,
    ShareLinkView,
)
from app_core.permission.ports.share_link_repository import ShareLinkRepository


class ShareLinkAdministration:
    def __init__(
        self,
        repository: ShareLinkRepository,
        *,
        now=lambda: datetime.now(UTC),
        token_factory=secrets.token_urlsafe,
    ) -> None:
        self._repository = repository
        self._now = now
        self._token_factory = token_factory

    async def create_share_link(
        self,
        actor_id: UUID,
        resource_id: UUID,
        idempotency_key: str,
        expires_at: datetime | None = None,
    ) -> CreatedShareLink:
        self._validate_expiry(expires_at)
        token_hash, share_url = self._new_secret()
        return await self._repository.create_share_link(
            actor_id,
            resource_id,
            token_hash,
            share_url,
            expires_at,
            idempotency_key,
        )

    async def list_share_links(
        self, actor_id: UUID, resource_id: UUID
    ) -> list[ShareLinkView]:
        return await self._repository.list_share_links(actor_id, resource_id)

    async def get_share_link(
        self, actor_id: UUID, resource_id: UUID, share_id: UUID
    ) -> ShareLinkView:
        return await self._repository.get_share_link(actor_id, resource_id, share_id)

    async def set_share_link_expiry(
        self,
        actor_id: UUID,
        resource_id: UUID,
        share_id: UUID,
        expires_at: datetime | None,
        idempotency_key: str,
    ) -> ShareLinkView:
        self._validate_expiry(expires_at)
        return await self._repository.set_share_link_expiry(
            actor_id,
            resource_id,
            share_id,
            expires_at,
            idempotency_key,
        )

    async def revoke_share_link(
        self,
        actor_id: UUID,
        resource_id: UUID,
        share_id: UUID,
        idempotency_key: str,
    ) -> ShareLinkView:
        return await self._repository.revoke_share_link(
            actor_id, resource_id, share_id, idempotency_key
        )

    async def regenerate_share_link(
        self,
        actor_id: UUID,
        resource_id: UUID,
        share_id: UUID,
        expires_at: datetime | None,
        idempotency_key: str,
    ) -> CreatedShareLink:
        self._validate_expiry(expires_at)
        token_hash, share_url = self._new_secret()
        return await self._repository.regenerate_share_link(
            actor_id,
            resource_id,
            share_id,
            token_hash,
            share_url,
            expires_at,
            idempotency_key,
        )

    async def resolve_public_share(self, token: str) -> AnonymousShareGrant | None:
        if not token or len(token) > 256:
            return None
        token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
        return await self._repository.resolve_share_token(token_hash)

    def _new_secret(self) -> tuple[str, str]:
        token = self._token_factory(32)
        return hashlib.sha256(token.encode("utf-8")).hexdigest(), self._share_url(token)

    @staticmethod
    def _share_url(token: str) -> str:
        return f"/share/{quote(token, safe='')}"

    def _validate_expiry(self, expires_at: datetime | None) -> None:
        if expires_at is None:
            return
        if expires_at.tzinfo is None or expires_at.utcoffset() is None:
            raise ValidationError(
                "Share expiry must include a time zone.",
                "SHARE_EXPIRY_INVALID",
                "expiresAt",
            )
        if expires_at <= self._now():
            raise ValidationError(
                "Share expiry must be in the future.",
                "SHARE_EXPIRY_INVALID",
                "expiresAt",
            )
