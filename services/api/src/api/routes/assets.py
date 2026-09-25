from __future__ import annotations

from typing import Annotated
from urllib.parse import quote
from uuid import UUID

from app_core.assets.application import DownloadAsset, ListResourceAssets, UploadAsset
from app_core.assets.domain import AssetError
from app_core.resource.domain import ResourcePermissionDeniedError
from app_core.session.domain.session import Session
from app_infra.postgres.asset_repository import PostgresAssetRepository
from app_infra.postgres.asset_upload_idempotency_repository import (
    PostgresAssetUploadIdempotencyRepository,
)
from app_infra.postgres.resource_ownership_repository import (
    PostgresResourceOwnershipRepository,
)
from fastapi import APIRouter, Depends, File, Form, Header, HTTPException, UploadFile
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from api.dependencies.auth import get_current_session, get_db_session
from api.infra.asset_storage import get_asset_store, safe_original_name

router = APIRouter()


@router.post(
    "/resources/{resource_id}/assets",
    status_code=201,
)
async def upload_asset(
    resource_id: UUID,
    current: Annotated[Session, Depends(get_current_session)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
    file: Annotated[UploadFile, File()],
    idempotency_key: Annotated[UUID, Header(alias="Idempotency-Key")],
    mime: Annotated[str | None, Form()] = None,
) -> dict:
    ownership = PostgresResourceOwnershipRepository(session)
    use_case = UploadAsset(
        PostgresAssetRepository(session),
        get_asset_store(),
        ownership,
        PostgresAssetUploadIdempotencyRepository(session),
    )
    data = await file.read()
    try:
        asset = await use_case.execute(
            current.account_id,
            resource_id,
            idempotency_key=str(idempotency_key),
            data=data,
            mime=mime or file.content_type,
            original_name=safe_original_name(file.filename),
        )
    except (AssetError, ResourcePermissionDeniedError):
        raise HTTPException(status_code=403, detail="RESOURCE_PERMISSION_DENIED")
    return {
        "assetId": str(asset.asset_id),
        "sha256": asset.sha256,
        "sizeBytes": asset.size_bytes,
    }


@router.get("/resources/{resource_id}/assets")
async def list_resource_assets(
    resource_id: UUID,
    current: Annotated[Session, Depends(get_current_session)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> dict:
    use_case = ListResourceAssets(
        PostgresAssetRepository(session),
        PostgresResourceOwnershipRepository(session),
    )
    try:
        assets = await use_case.execute(current.account_id, resource_id)
    except (AssetError, ResourcePermissionDeniedError):
        raise HTTPException(status_code=403, detail="RESOURCE_PERMISSION_DENIED")
    return {
        "resourceId": str(resource_id),
        "assets": [
            {
                "assetId": str(asset.asset_id),
                "originalName": asset.original_name,
                "mime": asset.mime,
                "sizeBytes": asset.size_bytes,
                "sha256": asset.sha256,
                "createdAt": asset.created_at,
            }
            for asset in assets
        ],
    }


@router.get("/assets/{asset_id}")
async def download_asset(
    asset_id: UUID,
    current: Annotated[Session, Depends(get_current_session)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> StreamingResponse:
    use_case = DownloadAsset(
        PostgresAssetRepository(session),
        get_asset_store(),
        PostgresResourceOwnershipRepository(session),
    )
    try:
        asset, data = await use_case.execute(current.account_id, asset_id)
    except (AssetError, ResourcePermissionDeniedError):
        raise HTTPException(status_code=403, detail="RESOURCE_PERMISSION_DENIED")
    except LookupError:
        raise HTTPException(status_code=404, detail="ASSET_NOT_FOUND")
    safe_mime = asset.mime or "application/octet-stream"
    if "\r" in safe_mime or "\n" in safe_mime:
        safe_mime = "application/octet-stream"
    inline_mimes = {"image/avif", "image/gif", "image/jpeg", "image/png", "image/webp"}
    disposition = "inline" if safe_mime.lower() in inline_mimes else "attachment"
    original_name = safe_original_name(asset.original_name)
    ascii_name = original_name.encode("ascii", "replace").decode("ascii")
    ascii_name = ascii_name.replace('"', "_")
    return StreamingResponse(
        iter([data]),
        media_type=safe_mime,
        headers={
            "Content-Disposition": (
                f'{disposition}; filename="{ascii_name}"; '
                f"filename*=UTF-8''{quote(original_name, safe='')}"
            ),
            "Content-Length": str(len(data)),
            "X-Asset-Id": str(asset.asset_id),
            "X-Asset-Sha256": asset.sha256,
            "X-Content-Type-Options": "nosniff",
        },
    )
