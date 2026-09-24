from __future__ import annotations

import os
import tempfile
from pathlib import Path
from typing import Annotated
from uuid import UUID

from app_core.assets.application import DownloadAsset, UploadAsset
from app_core.assets.domain import AssetError
from app_core.resource.domain import ResourcePermissionDeniedError
from app_core.session.domain.session import Session
from app_infra.postgres.asset_repository import PostgresAssetRepository
from app_infra.postgres.local_asset_store import LocalDiskAssetStore
from app_infra.postgres.resource_ownership_repository import (
    PostgresResourceOwnershipRepository,
)
from app_infra.postgres.s3_asset_store import S3AssetStore, S3StoreError
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from api.dependencies.auth import get_current_session, get_db_session

router = APIRouter()

_STORE_ROOT = Path(tempfile.gettempdir()) / "dom-assets"


def _asset_store() -> S3AssetStore | LocalDiskAssetStore:
    """Env-driven provider (arch 12): S3 when fully configured; a disk store
    otherwise. Partial S3 env is an explicit error, never a silent fallback."""
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


@router.post(
    "/resources/{resource_id}/assets",
    status_code=201,
)
async def upload_asset(
    resource_id: UUID,
    current: Annotated[Session, Depends(get_current_session)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
    file: Annotated[UploadFile, File()],
    mime: Annotated[str | None, Form()] = None,
) -> dict:
    use_case = UploadAsset(
        PostgresAssetRepository(session),
        _asset_store(),
        PostgresResourceOwnershipRepository(session),
    )
    data = await file.read()
    try:
        asset = await use_case.execute(
            current.account_id, resource_id, data=data, mime=mime
        )
    except (AssetError, ResourcePermissionDeniedError):
        raise HTTPException(status_code=403, detail="RESOURCE_PERMISSION_DENIED")
    return {
        "assetId": str(asset.asset_id),
        "sha256": asset.sha256,
        "sizeBytes": asset.size_bytes,
    }


@router.get("/assets/{asset_id}")
async def download_asset(
    asset_id: UUID,
    current: Annotated[Session, Depends(get_current_session)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> dict:
    use_case = DownloadAsset(
        PostgresAssetRepository(session),
        _asset_store(),
        PostgresResourceOwnershipRepository(session),
    )
    try:
        asset, data = await use_case.execute(current.account_id, asset_id)
    except (AssetError, ResourcePermissionDeniedError):
        raise HTTPException(status_code=403, detail="RESOURCE_PERMISSION_DENIED")
    except LookupError:
        raise HTTPException(status_code=404, detail="ASSET_NOT_FOUND")
    return {
        "assetId": str(asset.asset_id),
        "mime": asset.mime,
        "sha256": asset.sha256,
        "sizeBytes": len(data),
        "dataB64": __import__("base64").b64encode(data).decode(),
    }
