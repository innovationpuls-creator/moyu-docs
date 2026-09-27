from __future__ import annotations

import os
import tempfile
from pathlib import Path
from uuid import UUID

from app_core.assets.ports import AssetStore
from app_core.import_export.ports import TemporaryAssetStore
from sqlalchemy.ext.asyncio import AsyncSession

from app_infra.postgres.local_asset_store import LocalDiskAssetStore
from app_infra.postgres.s3_asset_store import S3AssetStore, S3StoreError


def configured_asset_store() -> AssetStore:
    endpoint = os.environ.get("S3_ASSET_ENDPOINT", "")
    region = os.environ.get("S3_ASSET_REGION", "")
    access = os.environ.get("S3_ASSET_ACCESS_KEY", "")
    secret = os.environ.get("S3_ASSET_SECRET_KEY", "")
    bucket = os.environ.get("S3_ASSET_BUCKET", "")
    addressing_style = os.environ.get("S3_ASSET_ADDRESSING_STYLE", "path")
    configured = [endpoint, region, access, secret, bucket]
    if any(configured) and not all(configured):
        raise S3StoreError("partial S3 asset configuration; set all S3_ASSET_*")
    if all(configured):
        return S3AssetStore(
            endpoint_url=endpoint,
            region=region,
            access_key=access,
            secret_key=secret,
            bucket=bucket,
            addressing_style=addressing_style,
        )
    return LocalDiskAssetStore(Path(tempfile.gettempdir()) / "dom-assets")


class ImportExportTemporaryAssetStore(TemporaryAssetStore):
    """Session-scoped temporary objects in the configured AssetStore."""

    def __init__(self, store: AssetStore) -> None:
        self._store = store

    async def put_import_source(self, asset_id: UUID, data: bytes) -> None:
        await self._run(self._store.put, _key("imports", asset_id), data)

    async def get_import_source(self, asset_id: UUID) -> bytes:
        return await self._run(self._store.get, _key("imports", asset_id))

    async def delete_import_source(self, asset_id: UUID) -> None:
        await self._run(self._store.delete, _key("imports", asset_id))

    async def put_export_result(self, asset_id: UUID, data: bytes) -> None:
        await self._run(self._store.put, _key("exports", asset_id), data)

    async def get_export_result(self, asset_id: UUID) -> bytes:
        return await self._run(self._store.get, _key("exports", asset_id))

    async def delete_export_result(self, asset_id: UUID) -> None:
        await self._run(self._store.delete, _key("exports", asset_id))

    async def _run(self, operation, *args):
        try:
            return await operation(*args)
        except S3StoreError as exc:
            raise OSError("temporary AssetStore operation failed") from exc


class TransactionReleasingTemporaryAssetStore(TemporaryAssetStore):
    """Release read-only API transactions while the object store is active."""

    def __init__(self, store: TemporaryAssetStore, session: AsyncSession) -> None:
        self._store = store
        self._session = session

    async def put_import_source(self, asset_id: UUID, data: bytes) -> None:
        await self._run(self._store.put_import_source, asset_id, data)

    async def get_import_source(self, asset_id: UUID) -> bytes:
        return await self._run(self._store.get_import_source, asset_id)

    async def delete_import_source(self, asset_id: UUID) -> None:
        await self._run(self._store.delete_import_source, asset_id)

    async def put_export_result(self, asset_id: UUID, data: bytes) -> None:
        await self._run(self._store.put_export_result, asset_id, data)

    async def get_export_result(self, asset_id: UUID) -> bytes:
        return await self._run(self._store.get_export_result, asset_id)

    async def delete_export_result(self, asset_id: UUID) -> None:
        await self._run(self._store.delete_export_result, asset_id)

    async def _run(self, operation, *args):
        if self._session.in_transaction():
            await self._session.commit()
        return await operation(*args)


def _key(kind: str, asset_id: UUID) -> str:
    if kind not in {"imports", "exports"}:
        raise ValueError("unsupported temporary asset kind")
    return f"tmp/import-export/{kind}/{asset_id}"
