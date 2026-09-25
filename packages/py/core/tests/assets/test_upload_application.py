from __future__ import annotations

from collections.abc import Awaitable, Callable
from uuid import UUID, uuid4

import pytest
from app_core.assets.application import UploadAsset
from app_core.assets.domain import Asset
from app_core.common.exceptions import IdempotencyConflictError


class _MemoryAssets:
    def __init__(self) -> None:
        self.saved: list[Asset] = []

    async def save(self, asset: Asset) -> Asset:
        self.saved.append(asset)
        return asset

    async def find_by_id(self, asset_id: UUID) -> Asset | None:
        return next((asset for asset in self.saved if asset.asset_id == asset_id), None)

    async def list_by_resource(self, resource_id: UUID) -> list[Asset]:
        return [asset for asset in self.saved if asset.resource_id == resource_id]


class _MemoryStore:
    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}
        self.puts: list[str] = []
        self.deletes: list[str] = []

    async def put(self, storage_key: str, data: bytes) -> None:
        self.puts.append(storage_key)
        self.objects[storage_key] = data

    async def get(self, storage_key: str) -> bytes:
        return self.objects[storage_key]

    async def delete(self, storage_key: str) -> None:
        self.deletes.append(storage_key)
        self.objects.pop(storage_key, None)


class _MemoryOwnership:
    async def authorize(self, actor_id: UUID, scope_id: UUID, operation: str) -> bool:
        return True


class _MemoryIdempotency:
    def __init__(self) -> None:
        self.records: dict[str, tuple[str, Asset]] = {}
        self.operations: list[str] = []

    async def execute(
        self,
        key: str,
        request_fingerprint: str,
        operation: Callable[[], Awaitable[Asset]],
    ) -> Asset:
        stored = self.records.get(key)
        if stored is not None:
            fingerprint, asset = stored
            if fingerprint != request_fingerprint:
                raise IdempotencyConflictError()
            return asset
        self.operations.append(key)
        asset = await operation()
        self.records[key] = (request_fingerprint, asset)
        return asset


@pytest.mark.asyncio
async def test_upload_replays_original_asset_for_same_key_and_request() -> None:
    repository = _MemoryAssets()
    store = _MemoryStore()
    idempotency = _MemoryIdempotency()
    upload = UploadAsset(repository, store, _MemoryOwnership(), idempotency)
    actor_id, resource_id = uuid4(), uuid4()

    first = await upload.execute(
        actor_id,
        resource_id,
        idempotency_key="key-1",
        data=b"image bytes",
        mime="image/png",
        original_name="diagram.png",
    )
    replay = await upload.execute(
        actor_id,
        resource_id,
        idempotency_key="key-1",
        data=b"image bytes",
        mime="image/png",
        original_name="diagram.png",
    )

    assert replay == first
    assert first.asset_id.version == 7
    assert len(repository.saved) == len(store.puts) == 1
    assert idempotency.operations == [f"{actor_id}:{resource_id}:key-1"]


@pytest.mark.asyncio
async def test_upload_rejects_reused_key_with_different_payload() -> None:
    repository = _MemoryAssets()
    store = _MemoryStore()
    upload = UploadAsset(repository, store, _MemoryOwnership(), _MemoryIdempotency())
    actor_id, resource_id = uuid4(), uuid4()
    await upload.execute(
        actor_id,
        resource_id,
        idempotency_key="key-2",
        data=b"first payload",
        mime="image/png",
        original_name="diagram.png",
    )

    with pytest.raises(IdempotencyConflictError) as error:
        await upload.execute(
            actor_id,
            resource_id,
            idempotency_key="key-2",
            data=b"different payload",
            mime="image/png",
            original_name="diagram.png",
        )

    assert error.value.error_code == "IDEMPOTENCY_KEY_CONFLICT"
    assert len(repository.saved) == len(store.puts) == 1
