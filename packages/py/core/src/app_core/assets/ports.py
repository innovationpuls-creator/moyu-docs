from __future__ import annotations

from typing import Protocol
from uuid import UUID

from app_core.assets.domain import Asset


class AssetStore(Protocol):
    async def put(self, storage_key: str, data: bytes) -> None: ...
    async def get(self, storage_key: str) -> bytes: ...
    async def delete(self, storage_key: str) -> None: ...


class AssetsRepository(Protocol):
    async def save(self, asset: Asset) -> Asset: ...
    async def find_by_id(self, asset_id: UUID) -> Asset | None: ...
