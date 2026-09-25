from __future__ import annotations

from typing import Annotated
from urllib.parse import quote
from uuid import UUID

from app_contracts.commands.permission.create_resource_share_link import (
    CreateResourceShareLink as CreateResourceShareLinkRequest,
)
from app_contracts.commands.permission.create_resource_share_link import (
    CreateResourceShareLinkResponse,
)
from app_contracts.commands.permission.regenerate_resource_share_link import (
    RegenerateResourceShareLink as RegenerateResourceShareLinkRequest,
)
from app_contracts.commands.permission.regenerate_resource_share_link import (
    RegenerateResourceShareLinkResponse,
)
from app_contracts.commands.permission.revoke_resource_share_link import (
    RevokeResourceShareLinkResponse,
)
from app_contracts.commands.permission.set_resource_share_link_expiry import (
    SetResourceShareLinkExpiry as SetResourceShareLinkExpiryRequest,
)
from app_contracts.commands.permission.set_resource_share_link_expiry import (
    SetResourceShareLinkExpiryResponse,
)
from app_contracts.queries.permission.list_resource_share_links import (
    ListResourceShareLinksResponse,
    ShareLinkMetadata,
)
from app_contracts.queries.permission.list_resource_share_links import (
    Status as ShareLinkContractStatus,
)
from app_contracts.queries.permission.open_public_shared_resource import (
    OpenPublicSharedResourceResponse,
)
from app_contracts.queries.permission.open_public_shared_resource import (
    ResourceType as PublicResourceType,
)
from app_core.assets.application import DownloadAsset
from app_core.assets.domain import AssetError
from app_core.permission.application.share_links import ShareLinkAdministration
from app_core.permission.domain.access_control import PermissionCapability
from app_core.permission.domain.share_link import (
    AnonymousShareGrant,
    ShareLinkView,
)
from app_core.resource.application import ExportResource as ExportResourceUseCase
from app_core.resource.application import ReadCurrentResourceContent
from app_core.resource.domain import ResourcePermissionDeniedError
from app_core.session.domain.session import Session
from app_infra.postgres.asset_repository import PostgresAssetRepository
from app_infra.postgres.resource.checkpoint_repository import (
    PostgresCheckpointRepository,
)
from app_infra.postgres.resource.journal_repository import PostgresJournalRepository
from app_infra.postgres.resource.resource_repository import PostgresResourceRepository
from fastapi import APIRouter, Depends, Header, HTTPException, Response, status
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from api.dependencies.auth import get_current_session, get_db_session
from api.dependencies.share_links import get_share_link_administration
from api.infra.asset_storage import get_asset_store, safe_original_name

router = APIRouter()
_ANONYMOUS_SHARE_ACTOR_ID = UUID(int=0)


class _AnonymousShareReadOnlyOwnership:
    """Adapt one verified Share grant to Resource's read-only permission port."""

    def __init__(self, grant: AnonymousShareGrant) -> None:
        self._grant = grant

    async def authorize(self, _actor_id: UUID, scope_id: UUID, operation: str) -> bool:
        return (
            scope_id == self._grant.resource_id
            and operation == PermissionCapability.READ.value
            and self._grant.allows(PermissionCapability.READ)
        )


def _share_link_metadata(view: ShareLinkView) -> ShareLinkMetadata:
    return ShareLinkMetadata(
        shareId=view.share_id,
        resourceId=view.resource_id,
        capability=view.capability.value,
        status=ShareLinkContractStatus(view.status.value),
        expiresAt=view.expires_at,
        createdBy=view.created_by,
        createdAt=view.created_at,
        revokedAt=view.revoked_at,
    )


@router.post(
    "/resources/{resource_id}/share-links",
    response_model=CreateResourceShareLinkResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_resource_share_link(
    resource_id: UUID,
    body: CreateResourceShareLinkRequest,
    current: Annotated[Session, Depends(get_current_session)],
    administration: Annotated[
        ShareLinkAdministration, Depends(get_share_link_administration)
    ],
    idempotency_key: Annotated[UUID, Header(alias="Idempotency-Key")],
) -> CreateResourceShareLinkResponse:
    created = await administration.create_share_link(
        current.account_id,
        resource_id,
        str(idempotency_key),
        body.expiresAt,
    )
    return CreateResourceShareLinkResponse(
        shareLink=_share_link_metadata(created.share_link),
        shareUrl=created.share_url,
    )


@router.get(
    "/resources/{resource_id}/share-links",
    response_model=ListResourceShareLinksResponse,
)
async def list_resource_share_links(
    resource_id: UUID,
    current: Annotated[Session, Depends(get_current_session)],
    administration: Annotated[
        ShareLinkAdministration, Depends(get_share_link_administration)
    ],
) -> ListResourceShareLinksResponse:
    views = await administration.list_share_links(current.account_id, resource_id)
    return ListResourceShareLinksResponse(
        resourceId=resource_id,
        shareLinks=[_share_link_metadata(view) for view in views],
    )


@router.patch(
    "/resources/{resource_id}/share-links/{share_id}",
    response_model=SetResourceShareLinkExpiryResponse,
)
async def set_resource_share_link_expiry(
    resource_id: UUID,
    share_id: UUID,
    body: SetResourceShareLinkExpiryRequest,
    current: Annotated[Session, Depends(get_current_session)],
    administration: Annotated[
        ShareLinkAdministration, Depends(get_share_link_administration)
    ],
    idempotency_key: Annotated[UUID, Header(alias="Idempotency-Key")],
) -> SetResourceShareLinkExpiryResponse:
    view = await administration.set_share_link_expiry(
        current.account_id,
        resource_id,
        share_id,
        body.expiresAt,
        str(idempotency_key),
    )
    return SetResourceShareLinkExpiryResponse(shareLink=_share_link_metadata(view))


@router.delete(
    "/resources/{resource_id}/share-links/{share_id}",
    response_model=RevokeResourceShareLinkResponse,
)
async def revoke_resource_share_link(
    resource_id: UUID,
    share_id: UUID,
    current: Annotated[Session, Depends(get_current_session)],
    administration: Annotated[
        ShareLinkAdministration, Depends(get_share_link_administration)
    ],
    idempotency_key: Annotated[UUID, Header(alias="Idempotency-Key")],
) -> RevokeResourceShareLinkResponse:
    view = await administration.revoke_share_link(
        current.account_id, resource_id, share_id, str(idempotency_key)
    )
    return RevokeResourceShareLinkResponse(shareLink=_share_link_metadata(view))


@router.post(
    "/resources/{resource_id}/share-links/{share_id}/regenerate",
    response_model=RegenerateResourceShareLinkResponse,
)
async def regenerate_resource_share_link(
    resource_id: UUID,
    share_id: UUID,
    body: RegenerateResourceShareLinkRequest,
    current: Annotated[Session, Depends(get_current_session)],
    administration: Annotated[
        ShareLinkAdministration, Depends(get_share_link_administration)
    ],
    idempotency_key: Annotated[UUID, Header(alias="Idempotency-Key")],
) -> RegenerateResourceShareLinkResponse:
    created = await administration.regenerate_share_link(
        current.account_id,
        resource_id,
        share_id,
        body.expiresAt,
        str(idempotency_key),
    )
    return RegenerateResourceShareLinkResponse(
        shareLink=_share_link_metadata(created.share_link),
        shareUrl=created.share_url,
    )


@router.get(
    "/public/shares/{token}",
    response_model=OpenPublicSharedResourceResponse,
)
async def open_public_shared_resource(
    token: str,
    response: Response,
    administration: Annotated[
        ShareLinkAdministration, Depends(get_share_link_administration)
    ],
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> OpenPublicSharedResourceResponse:
    response.headers["Cache-Control"] = "no-store"
    response.headers["Pragma"] = "no-cache"
    grant = await administration.resolve_public_share(token)
    if grant is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="SHARE_LINK_NOT_FOUND",
            headers={"Cache-Control": "no-store", "Pragma": "no-cache"},
        )
    use_case = ExportResourceUseCase(
        PostgresResourceRepository(session),
        PostgresCheckpointRepository(session),
        _AnonymousShareReadOnlyOwnership(grant),
    )
    try:
        document = await use_case.execute(
            _ANONYMOUS_SHARE_ACTOR_ID, grant.resource_id
        )
    except (LookupError, ResourcePermissionDeniedError):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="SHARE_LINK_NOT_FOUND",
            headers={"Cache-Control": "no-store", "Pragma": "no-cache"},
        )
    return OpenPublicSharedResourceResponse(
        resourceId=UUID(document["resource"]["resourceId"]),
        name=document["resource"]["name"],
        resourceType=PublicResourceType(document["resource"]["resourceType"]),
        snapshot=document["content"]["snapshot"],
        journalSeq=document["content"]["journalSeq"],
    )


@router.get("/public/shares/{token}/assets/{asset_id}")
async def download_public_shared_asset(
    token: str,
    asset_id: UUID,
    response: Response,
    administration: Annotated[
        ShareLinkAdministration, Depends(get_share_link_administration)
    ],
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> StreamingResponse:
    response.headers["Cache-Control"] = "no-store"
    response.headers["Pragma"] = "no-cache"
    grant = await administration.resolve_public_share(token)
    if grant is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="SHARE_LINK_NOT_FOUND",
            headers={"Cache-Control": "no-store", "Pragma": "no-cache"},
        )
    current = ReadCurrentResourceContent(
        PostgresResourceRepository(session),
        PostgresJournalRepository(session),
        PostgresCheckpointRepository(session),
        _AnonymousShareReadOnlyOwnership(grant),
    )
    try:
        await current.execute(_ANONYMOUS_SHARE_ACTOR_ID, grant.resource_id)
        asset, data = await DownloadAsset(
            PostgresAssetRepository(session),
            get_asset_store(),
            _AnonymousShareReadOnlyOwnership(grant),
        ).execute(_ANONYMOUS_SHARE_ACTOR_ID, asset_id)
    except (LookupError, AssetError, ResourcePermissionDeniedError):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="SHARED_ASSET_NOT_FOUND",
            headers={"Cache-Control": "no-store", "Pragma": "no-cache"},
        )
    media_type = asset.mime or "application/octet-stream"
    if "\r" in media_type or "\n" in media_type:
        media_type = "application/octet-stream"
    inline_types = {"image/avif", "image/gif", "image/jpeg", "image/png", "image/webp"}
    disposition = "inline" if media_type.lower() in inline_types else "attachment"
    filename = safe_original_name(asset.original_name)
    ascii_filename = (
        filename.encode("ascii", "replace").decode("ascii").replace('"', "_")
    )
    return StreamingResponse(
        iter([data]),
        media_type=media_type,
        headers={
            "Cache-Control": "no-store",
            "Pragma": "no-cache",
            "Content-Disposition": (
                f'{disposition}; filename="{ascii_filename}"; '
                f"filename*=UTF-8''{quote(filename, safe='')}"
            ),
            "Content-Length": str(len(data)),
            "X-Asset-Id": str(asset.asset_id),
            "X-Asset-Sha256": asset.sha256,
            "X-Content-Type-Options": "nosniff",
        },
    )
