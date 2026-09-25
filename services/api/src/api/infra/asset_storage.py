from __future__ import annotations

import os
import tempfile
import unicodedata
from pathlib import Path

from app_core.assets.ports import AssetStore
from app_infra.postgres.local_asset_store import LocalDiskAssetStore
from app_infra.postgres.s3_asset_store import S3AssetStore, S3StoreError

_STORE_ROOT = Path(tempfile.gettempdir()) / "dom-assets"


def safe_original_name(value: str | None) -> str:
    cleaned = "".join(
        char
        for char in (value or "")
        if char not in "/\\" and unicodedata.category(char)[0] != "C"
    ).strip(" .")
    return cleaned[:255] or "attachment"


def get_asset_store() -> AssetStore:
    """Build the configured asset provider without introducing a fallback."""
    endpoint = os.environ.get("S3_ASSET_ENDPOINT", "")
    region = os.environ.get("S3_ASSET_REGION", "")
    access = os.environ.get("S3_ASSET_ACCESS_KEY", "")
    secret = os.environ.get("S3_ASSET_SECRET_KEY", "")
    bucket = os.environ.get("S3_ASSET_BUCKET", "")
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
        )
    return LocalDiskAssetStore(_STORE_ROOT)
