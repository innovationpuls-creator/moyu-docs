from __future__ import annotations

import hashlib
import json
from uuid import UUID

from app_core.assets.domain import Asset
from app_core.assets.ports import (
    AssetsRepository,
    AssetStore,
    AssetUploadIdempotencyPort,
)
from app_core.common.ids import new_uuid7
from app_core.resource.ports import ReadOnlyResourceOwnershipPort


class UploadAsset:
    def __init__(
        self,
        assets: AssetsRepository,
        store: AssetStore,
        ownership: ReadOnlyResourceOwnershipPort,
        idempotency: AssetUploadIdempotencyPort,
    ) -> None:
        self._assets = assets
        self._store = store
        self._ownership = ownership
        self._idempotency = idempotency

    async def execute(
        self,
        actor_id: UUID,
        resource_id: UUID,
        *,
        idempotency_key: str,
        data: bytes,
        mime: str | None,
        original_name: str = "attachment",
    ) -> Asset:
        if not await self._ownership.authorize(
            actor_id, resource_id, "resource.update"
        ):
            from app_core.assets.domain import AssetError

            raise AssetError("no resource.update permission")
        sha = hashlib.sha256(data).hexdigest()
        fingerprint = hashlib.sha256(
            json.dumps(
                {
                    "actorId": str(actor_id),
                    "resourceId": str(resource_id),
                    "sha256": sha,
                    "sizeBytes": len(data),
                    "mime": mime,
                    "originalName": original_name,
                },
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
        attempted_storage_key: str | None = None

        async def create_asset() -> Asset:
            nonlocal attempted_storage_key
            asset_id = new_uuid7()
            storage_scope = hashlib.sha256(
                f"{actor_id}:{resource_id}:{idempotency_key}".encode("utf-8")
            ).hexdigest()
            storage_key = f"assets/upload-idempotency/{storage_scope}"
            attempted_storage_key = storage_key
            await self._store.put(storage_key, data)
            asset = Asset(
                asset_id=asset_id,
                resource_id=resource_id,
                provider="local-disk",
                storage_key=storage_key,
                size_bytes=len(data),
                mime=mime,
                sha256=sha,
                created_by=actor_id,
                original_name=original_name,
            )
            return await self._assets.save(asset)

        try:
            return await self._idempotency.execute(
                f"{actor_id}:{resource_id}:{idempotency_key}",
                fingerprint,
                create_asset,
            )
        except BaseException:
            if attempted_storage_key is not None:
                await self._store.delete(attempted_storage_key)
            raise


class DownloadAsset:
    def __init__(
        self,
        assets: AssetsRepository,
        store: AssetStore,
        ownership: ReadOnlyResourceOwnershipPort,
    ) -> None:
        self._assets = assets
        self._store = store
        self._ownership = ownership

    async def execute(self, actor_id: UUID, asset_id: UUID) -> tuple[Asset, bytes]:
        asset = await self._assets.find_by_id(asset_id)
        if asset is None:
            raise LookupError("asset not found")
        if not await self._ownership.authorize(
            actor_id, asset.resource_id, "resource.read"
        ):
            from app_core.assets.domain import AssetError

            raise AssetError("no resource.read permission")
        data = await self._store.get(asset.storage_key)
        return asset, data


class ListResourceAssets:
    def __init__(
        self,
        assets: AssetsRepository,
        ownership: ReadOnlyResourceOwnershipPort,
    ) -> None:
        self._assets = assets
        self._ownership = ownership

    async def execute(self, actor_id: UUID, resource_id: UUID) -> list[Asset]:
        if not await self._ownership.authorize(actor_id, resource_id, "resource.read"):
            from app_core.assets.domain import AssetError

            raise AssetError("no resource.read permission")
        return await self._assets.list_by_resource(resource_id)
