from __future__ import annotations

import hashlib
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from app_core.common.exceptions import ValidationError
from app_core.permission.application.share_links import ShareLinkAdministration
from app_core.permission.domain.access_control import PermissionCapability
from app_core.permission.domain.share_link import (
    AnonymousShareGrant,
    CreatedShareLink,
    ShareCapability,
    ShareLinkStatus,
    ShareLinkView,
)


class ShareLinkRepository:
    def __init__(self) -> None:
        self.create_call = None
        self.regenerate_call = None
        self.resolve_call = None
        self.share_id = uuid4()
        self.resource_id = uuid4()
        self.actor_id = uuid4()

    async def create_share_link(
        self,
        actor_id,
        resource_id,
        token_hash,
        share_url,
        expires_at,
        idempotency_key,
    ):
        self.create_call = (
            actor_id,
            resource_id,
            token_hash,
            share_url,
            expires_at,
            idempotency_key,
        )
        return CreatedShareLink(self._view(resource_id, expires_at), share_url)

    async def list_share_links(self, actor_id, resource_id):
        return [self._view(resource_id, None)]

    async def get_share_link(self, actor_id, resource_id, share_id):
        return self._view(resource_id, None)

    async def set_share_link_expiry(
        self, actor_id, resource_id, share_id, expires_at, idempotency_key
    ):
        return self._view(resource_id, expires_at)

    async def revoke_share_link(self, actor_id, resource_id, share_id, idempotency_key):
        return ShareLinkView(
            self.share_id,
            resource_id,
            ShareCapability.READ,
            ShareLinkStatus.REVOKED,
            None,
            actor_id,
            datetime.now(UTC),
            datetime.now(UTC),
        )

    async def regenerate_share_link(
        self,
        actor_id,
        resource_id,
        share_id,
        token_hash,
        share_url,
        expires_at,
        idempotency_key,
    ):
        self.regenerate_call = (
            actor_id,
            resource_id,
            share_id,
            token_hash,
            share_url,
            expires_at,
            idempotency_key,
        )
        return CreatedShareLink(self._view(resource_id, expires_at), share_url)

    async def resolve_share_token(self, token_hash):
        self.resolve_call = token_hash
        return AnonymousShareGrant(self.share_id, self.resource_id)

    def _view(self, resource_id, expires_at):
        return ShareLinkView(
            self.share_id,
            resource_id,
            ShareCapability.READ,
            ShareLinkStatus.ACTIVE,
            expires_at,
            self.actor_id,
            datetime.now(UTC),
            None,
        )


@pytest.mark.asyncio
async def test_creation_returns_relative_link_and_only_sends_hash_to_repository() -> (
    None
):
    repository = ShareLinkRepository()
    actor_id, resource_id = uuid4(), uuid4()
    expiry = datetime(2026, 10, 1, tzinfo=UTC)
    administration = ShareLinkAdministration(
        repository,
        now=lambda: datetime(2026, 9, 25, tzinfo=UTC),
        token_factory=lambda _: "opaque/token",
    )

    created = await administration.create_share_link(
        actor_id, resource_id, "request-1", expiry
    )

    assert created.share_url == "/share/opaque%2Ftoken"
    assert repository.create_call == (
        actor_id,
        resource_id,
        hashlib.sha256(b"opaque/token").hexdigest(),
        created.share_url,
        expiry,
        "request-1",
    )
    assert "opaque/token" not in repr(created)


@pytest.mark.asyncio
async def test_expiry_must_be_future_and_timezone_aware() -> None:
    administration = ShareLinkAdministration(
        ShareLinkRepository(), now=lambda: datetime(2026, 9, 25, tzinfo=UTC)
    )

    with pytest.raises(ValidationError, match="time zone"):
        await administration.create_share_link(
            uuid4(), uuid4(), "naive", datetime(2026, 10, 1)
        )
    with pytest.raises(ValidationError, match="future"):
        await administration.create_share_link(
            uuid4(), uuid4(), "past", datetime(2026, 9, 24, tzinfo=UTC)
        )


@pytest.mark.asyncio
async def test_regeneration_hashes_a_new_secret_and_keeps_url_out_of_view() -> None:
    repository = ShareLinkRepository()
    administration = ShareLinkAdministration(
        repository,
        token_factory=lambda _: "new-secret",
    )

    regenerated = await administration.regenerate_share_link(
        repository.actor_id,
        repository.resource_id,
        repository.share_id,
        None,
        "rotate-1",
    )

    assert regenerated.share_url == "/share/new-secret"
    assert repository.regenerate_call is not None
    assert repository.regenerate_call[3] == hashlib.sha256(b"new-secret").hexdigest()
    assert "new-secret" not in repr(regenerated.share_link)


@pytest.mark.asyncio
async def test_public_resolution_hashes_token_and_grants_only_content_read() -> None:
    repository = ShareLinkRepository()
    administration = ShareLinkAdministration(repository)

    grant = await administration.resolve_public_share("opaque-token")

    assert repository.resolve_call == hashlib.sha256(b"opaque-token").hexdigest()
    assert grant is not None
    assert grant.allows(PermissionCapability.READ)
    assert not grant.allows(PermissionCapability.EDIT)
    assert not grant.allows(PermissionCapability.COMMENT)
    assert not grant.can_participate_in_presence


@pytest.mark.asyncio
async def test_invalid_public_tokens_are_rejected_without_repository_lookup() -> None:
    repository = ShareLinkRepository()
    administration = ShareLinkAdministration(repository)

    assert await administration.resolve_public_share("") is None
    assert await administration.resolve_public_share("x" * 257) is None
    assert repository.resolve_call is None


@pytest.mark.asyncio
async def test_management_views_never_include_the_share_url() -> None:
    repository = ShareLinkRepository()
    administration = ShareLinkAdministration(repository)
    actor_id, resource_id, share_id = uuid4(), uuid4(), repository.share_id
    expiry = datetime.now(UTC) + timedelta(days=1)

    listed = await administration.list_share_links(actor_id, resource_id)
    status = await administration.get_share_link(actor_id, resource_id, share_id)
    changed = await administration.set_share_link_expiry(
        actor_id, resource_id, share_id, expiry, "expiry-1"
    )
    revoked = await administration.revoke_share_link(
        actor_id, resource_id, share_id, "revoke-1"
    )

    assert listed[0].status is ShareLinkStatus.ACTIVE
    assert status.status is ShareLinkStatus.ACTIVE
    assert changed.expires_at == expiry
    assert revoked.status is ShareLinkStatus.REVOKED
    assert all(not hasattr(view, "share_url") for view in [*listed, status, changed])
