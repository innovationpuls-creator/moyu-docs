from __future__ import annotations

from datetime import datetime
from typing import Protocol
from uuid import UUID

from app_core.permission.domain.share_link import (
    AnonymousShareGrant,
    CreatedShareLink,
    ShareLinkView,
)


class ShareLinkRepository(Protocol):
    async def create_share_link(
        self,
        actor_id: UUID,
        resource_id: UUID,
        token_hash: str,
        share_url: str,
        expires_at: datetime | None,
        idempotency_key: str,
    ) -> CreatedShareLink: ...

    async def list_share_links(
        self, actor_id: UUID, resource_id: UUID
    ) -> list[ShareLinkView]: ...

    async def get_share_link(
        self, actor_id: UUID, resource_id: UUID, share_id: UUID
    ) -> ShareLinkView: ...

    async def set_share_link_expiry(
        self,
        actor_id: UUID,
        resource_id: UUID,
        share_id: UUID,
        expires_at: datetime | None,
        idempotency_key: str,
    ) -> ShareLinkView: ...

    async def revoke_share_link(
        self,
        actor_id: UUID,
        resource_id: UUID,
        share_id: UUID,
        idempotency_key: str,
    ) -> ShareLinkView: ...

    async def regenerate_share_link(
        self,
        actor_id: UUID,
        resource_id: UUID,
        share_id: UUID,
        token_hash: str,
        share_url: str,
        expires_at: datetime | None,
        idempotency_key: str,
    ) -> CreatedShareLink: ...

    async def resolve_share_token(
        self, token_hash: str
    ) -> AnonymousShareGrant | None: ...
