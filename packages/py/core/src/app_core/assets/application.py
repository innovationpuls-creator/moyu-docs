from __future__ import annotations

import hashlib
from uuid import UUID, uuid4

from app_core.assets.domain import Asset
from app_core.assets.ports import AssetsRepository, AssetStore
from app_core.resource.ports import ReadOnlyResourceOwnershipPort


class UploadAsset:
    def __init__(
        self,
        assets: AssetsRepository,
        store: AssetStore,
        ownership: ReadOnlyResourceOwnershipPort,
    ) -> None:
        self._assets = assets
        self._store = store
        self._ownership = ownership

    async def execute(
        self,
        actor_id: UUID,
        resource_id: UUID,
        *,
        data: bytes,
        mime: str | None,
    ) -> Asset:
        if not await self._ownership.authorize(
            actor_id, resource_id, "resource.update"
        ):
            from app_core.assets.domain import AssetError

            raise AssetError("no resource.update permission")
        sha = hashlib.sha256(data).hexdigest()
        asset_id = uuid4()
        storage_key = f"assets/{asset_id}/{sha}"
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
        )
        return await self._assets.save(asset)


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
