from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from api.dependencies.auth import get_current_session, get_db_session
from api.dependencies.share_links import get_share_link_administration
from api.infra.broadcast import get_broadcast_publisher
from api.middleware.error_handler import register_error_handlers
from api.routes import share_links as share_link_routes
from api.routes.comments import router as comments_router
from api.routes.resource_write import router as resource_write_router
from app_core.assets.domain import Asset
from app_core.common.exceptions import AuthenticationError, PermissionDeniedError
from app_core.permission.domain.share_link import (
    AnonymousShareGrant,
    ShareCapability,
    ShareLinkStatus,
    ShareLinkView,
)
from app_core.resource.domain import Checkpoint, JournalOp, Resource, ResourceLifecycle
from app_core.session.domain.session import Session
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient


class StubShareLinkAdministration:
    def __init__(self, resource_id: UUID, authorized_actor: UUID) -> None:
        self.resource_id = resource_id
        self.authorized_actor = authorized_actor
        self.share_id = uuid4()
        self.created_at = datetime.now(UTC)
        self.active_token_valid = True
        self.resolved_tokens: list[str] = []

    async def list_share_links(self, actor_id: UUID, resource_id: UUID):
        self._authorize(actor_id)
        return [self._view(resource_id)]

    async def resolve_public_share(self, token: str):
        self.resolved_tokens.append(token)
        if token != "active-token" or not self.active_token_valid:
            return None
        return AnonymousShareGrant(uuid4(), self.resource_id)

    def _authorize(self, actor_id: UUID) -> None:
        if actor_id != self.authorized_actor:
            raise PermissionDeniedError("No Share Link management access.", "FORBIDDEN")

    def _view(self, resource_id: UUID) -> ShareLinkView:
        return ShareLinkView(
            self.share_id,
            resource_id,
            ShareCapability.READ,
            ShareLinkStatus.ACTIVE,
            None,
            self.authorized_actor,
            self.created_at,
            None,
        )


class StubResourceRepository:
    def __init__(self, resource_id: UUID) -> None:
        self.resource_id = resource_id

    async def get(self, resource_id: UUID) -> Resource | None:
        if resource_id != self.resource_id:
            return None
        return Resource(
            resource_id=resource_id,
            project_id=uuid4(),
            folder_id=None,
            resource_type="document",
            name="Shared document",
            normalized_name="shared-document",
            lifecycle=ResourceLifecycle.ACTIVE,
        )


class StubCheckpointRepository:
    def __init__(self, resource_id: UUID) -> None:
        self.resource_id = resource_id

    async def latest(self, resource_id: UUID) -> Checkpoint | None:
        if resource_id != self.resource_id:
            return None
        return Checkpoint(
            resource_id=resource_id,
            checkpoint_seq=1,
            base_journal_seq=8,
            snapshot={"nodes": [{"text": "public content"}]},
        )


class StubJournalRepository:
    def __init__(self, resource_id: UUID) -> None:
        self.resource_id = resource_id

    async def max_seq(self, resource_id: UUID) -> int:
        return 8 if resource_id == self.resource_id else 0

    async def read_cursor(self, resource_id: UUID, after_seq: int, *, limit: int = 200):
        now = datetime.now(UTC)
        operations = [
            JournalOp(
                resource_id=self.resource_id,
                journal_seq=seq,
                ownership_epoch=1,
                update_bytes=f"update-{seq}".encode(),
                update_hash=f"hash-{seq}",
                accepted_at=now,
                durable_at=now,
            )
            for seq in range(after_seq + 1, 9)
        ]
        return operations[:limit] if resource_id == self.resource_id else []


class StubAssetRepository:
    def __init__(self, asset: Asset) -> None:
        self.asset = asset

    async def find_by_id(self, asset_id: UUID) -> Asset | None:
        return self.asset if asset_id == self.asset.asset_id else None


class StubAssetStore:
    async def get(self, _storage_key: str) -> bytes:
        return b"shared-png-bytes"


def _session(account_id: UUID) -> Session:
    return Session.create(
        account_id=account_id, device_id="test-device", at=datetime.now(UTC)
    )


def _app(
    administration: StubShareLinkAdministration,
    actor_id: UUID,
) -> FastAPI:
    app = FastAPI()
    register_error_handlers(app)
    app.include_router(share_link_routes.router, prefix="/v1")
    app.dependency_overrides[get_current_session] = lambda: _session(actor_id)
    app.dependency_overrides[get_db_session] = lambda: object()
    app.dependency_overrides[get_share_link_administration] = lambda: administration
    return app


@pytest.mark.asyncio
async def test_public_share_revalidates_token_and_returns_no_store_content(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    owner_id, resource_id = uuid4(), uuid4()
    administration = StubShareLinkAdministration(resource_id, owner_id)
    monkeypatch.setattr(
        share_link_routes,
        "PostgresResourceRepository",
        lambda _session: StubResourceRepository(resource_id),
    )
    monkeypatch.setattr(
        share_link_routes,
        "PostgresCheckpointRepository",
        lambda _session: StubCheckpointRepository(resource_id),
    )
    monkeypatch.setattr(
        share_link_routes,
        "PostgresJournalRepository",
        lambda _session: StubJournalRepository(resource_id),
    )
    app = _app(administration, owner_id)

    async def reject_authenticated_session():
        raise AssertionError("public Share read must not require a Session")

    app.dependency_overrides[get_current_session] = reject_authenticated_session

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get("/v1/public/shares/active-token")
        administration.active_token_valid = False
        revoked = await client.get("/v1/public/shares/active-token")

    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["pragma"] == "no-cache"
    assert response.json() == {
        "resourceId": str(resource_id),
        "name": "Shared document",
        "resourceType": "document",
        "snapshot": {"nodes": [{"text": "public content"}]},
        "journalSeq": 8,
    }
    assert "active-token" not in response.text
    assert revoked.status_code == 404
    assert revoked.headers["cache-control"] == "no-store"
    assert administration.resolved_tokens == ["active-token", "active-token"]


@pytest.mark.asyncio
async def test_public_share_asset_is_inline_and_scoped_to_the_grant(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    owner_id, resource_id = uuid4(), uuid4()
    asset = Asset(
        asset_id=uuid4(),
        resource_id=resource_id,
        provider="local-disk",
        storage_key="asset-key",
        size_bytes=17,
        mime="image/png",
        sha256="a" * 64,
        created_by=owner_id,
        created_at=datetime.now(UTC),
        original_name="photo.png",
    )
    asset_repository = StubAssetRepository(asset)
    administration = StubShareLinkAdministration(resource_id, owner_id)
    monkeypatch.setattr(
        share_link_routes,
        "PostgresResourceRepository",
        lambda _session: StubResourceRepository(resource_id),
    )
    monkeypatch.setattr(
        share_link_routes,
        "PostgresCheckpointRepository",
        lambda _session: StubCheckpointRepository(resource_id),
    )
    monkeypatch.setattr(
        share_link_routes,
        "PostgresJournalRepository",
        lambda _session: StubJournalRepository(resource_id),
    )
    monkeypatch.setattr(
        share_link_routes,
        "PostgresAssetRepository",
        lambda _session: asset_repository,
    )
    monkeypatch.setattr(share_link_routes, "get_asset_store", lambda: StubAssetStore())
    app = _app(administration, owner_id)
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get(
            f"/v1/public/shares/active-token/assets/{asset.asset_id}"
        )
        asset_repository.asset = Asset(
            asset_id=asset.asset_id,
            resource_id=uuid4(),
            provider=asset.provider,
            storage_key=asset.storage_key,
            size_bytes=asset.size_bytes,
            mime=asset.mime,
            sha256=asset.sha256,
            created_by=asset.created_by,
            created_at=asset.created_at,
            original_name=asset.original_name,
        )
        foreign = await client.get(
            f"/v1/public/shares/active-token/assets/{asset.asset_id}"
        )

    assert response.status_code == 200
    assert response.content == b"shared-png-bytes"
    assert response.headers["content-disposition"].startswith("inline;")
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["x-content-type-options"] == "nosniff"
    assert foreign.status_code == 404


@pytest.mark.asyncio
@pytest.mark.parametrize("token", ["missing-token", "revoked-token", "expired-token"])
async def test_missing_revoked_or_expired_share_is_not_found_without_cache(
    token: str,
) -> None:
    actor_id, resource_id = uuid4(), uuid4()
    app = _app(StubShareLinkAdministration(resource_id, actor_id), actor_id)

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get(f"/v1/public/shares/{token}")

    assert response.status_code == 404
    assert response.headers["cache-control"] == "no-store"


@pytest.mark.asyncio
async def test_management_route_rejects_non_manager_actor() -> None:
    manager_id, reader_id, resource_id = uuid4(), uuid4(), uuid4()
    administration = StubShareLinkAdministration(resource_id, manager_id)
    app = _app(administration, reader_id)

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get(f"/v1/resources/{resource_id}/share-links")

    assert response.status_code == 403
    assert response.json()["errorCode"] == "FORBIDDEN"


@pytest.mark.asyncio
async def test_anonymous_share_has_no_comment_presence_or_write_routes() -> None:
    actor_id, resource_id = uuid4(), uuid4()
    app = _app(StubShareLinkAdministration(resource_id, actor_id), actor_id)
    app.include_router(comments_router, prefix="/v1")
    app.include_router(resource_write_router, prefix="/v1")

    async def reject_session() -> Session:
        raise AuthenticationError("An authenticated Session is required.")

    app.dependency_overrides[get_current_session] = reject_session
    app.dependency_overrides[get_broadcast_publisher] = lambda: object()

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        comments = await client.get("/v1/public/shares/active-token/comments")
        presence = await client.get("/v1/public/shares/active-token/presence")
        journal_read = await client.get(
            "/v1/public/shares/active-token/journal?afterSeq=0&throughSeq=8"
        )
        write = await client.post("/v1/public/shares/active-token/write")
        mutation = await client.post("/v1/public/shares/active-token")
        resource_comments = await client.get(f"/v1/resources/{resource_id}/comments")
        comment_write = await client.post(
            f"/v1/resources/{resource_id}/comments",
            json={
                "resourceId": str(resource_id),
                "body": "anonymous comment",
                "idempotencyKey": str(uuid4()),
            },
        )
        journal_write = await client.post(
            f"/v1/resources/{resource_id}/journal",
            json={
                "resourceId": str(resource_id),
                "update": "eA==",
                "idempotencyKey": str(uuid4()),
            },
        )

    assert comments.status_code == 404
    assert presence.status_code == 404
    assert journal_read.status_code == 404
    assert write.status_code == 404
    assert mutation.status_code == 405
    assert resource_comments.status_code == 401
    assert comment_write.status_code == 401
    assert journal_write.status_code == 401


@pytest.mark.asyncio
async def test_anonymous_read_adapter_grants_only_the_share_resource_read() -> None:
    resource_id = uuid4()
    grant = AnonymousShareGrant(uuid4(), resource_id)
    ownership = share_link_routes._AnonymousShareReadOnlyOwnership(grant)

    assert await ownership.authorize(UUID(int=0), resource_id, "resource.read")
    assert not await ownership.authorize(UUID(int=0), resource_id, "resource.update")
    assert not await ownership.authorize(UUID(int=0), resource_id, "resource.comment")
    assert not await ownership.authorize(UUID(int=0), uuid4(), "resource.read")
