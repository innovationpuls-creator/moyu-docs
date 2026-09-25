from __future__ import annotations

from uuid import uuid4

import pytest
from app_infra.postgres.import_export_storage import (
    ImportExportTemporaryAssetStore,
    S3StoreError,
)


class _AssetStore:
    def __init__(self) -> None:
        self.objects = {}
        self.fail_with: Exception | None = None

    async def put(self, key: str, data: bytes) -> None:
        if self.fail_with is not None:
            raise self.fail_with
        self.objects[key] = data

    async def get(self, key: str) -> bytes:
        if self.fail_with is not None:
            raise self.fail_with
        return self.objects[key]

    async def delete(self, key: str) -> None:
        if self.fail_with is not None:
            raise self.fail_with
        self.objects.pop(key, None)


@pytest.mark.asyncio
async def test_temporary_objects_use_session_scoped_keys() -> None:
    asset_id = uuid4()
    store = _AssetStore()
    temporary = ImportExportTemporaryAssetStore(store)

    await temporary.put_import_source(asset_id, b"import")
    await temporary.put_export_result(asset_id, b"export")

    assert store.objects == {
        f"tmp/import-export/imports/{asset_id}": b"import",
        f"tmp/import-export/exports/{asset_id}": b"export",
    }
    assert await temporary.get_import_source(asset_id) == b"import"
    assert await temporary.get_export_result(asset_id) == b"export"


@pytest.mark.asyncio
async def test_s3_errors_are_retryable_os_errors_at_temporary_boundary() -> None:
    store = _AssetStore()
    store.fail_with = S3StoreError("object storage unavailable")
    temporary = ImportExportTemporaryAssetStore(store)

    with pytest.raises(OSError, match="temporary AssetStore operation failed"):
        await temporary.put_export_result(uuid4(), b"payload")
