from __future__ import annotations

from typing import Any
from uuid import UUID

from app_core.assets.domain import Asset
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


class PostgresAssetRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def save(self, asset: Asset) -> Asset:
        row = (
            (
                await self._session.execute(
                    text(
                        "INSERT INTO collab.resource_assets "
                        "(asset_id,resource_id,provider,storage_key,size_bytes,"
                        "mime,sha256,created_by,original_name) "
                        "VALUES (:aid,:rid,:provider,:key,:size,:mime,:sha,:by,:name) "
                        "RETURNING *"
                    ),
                    {
                        "aid": asset.asset_id,
                        "rid": asset.resource_id,
                        "provider": asset.provider,
                        "key": asset.storage_key,
                        "size": asset.size_bytes,
                        "mime": asset.mime,
                        "sha": asset.sha256,
                        "by": asset.created_by,
                        "name": asset.original_name,
                    },
                )
            )
            .mappings()
            .one()
        )
        return _to_asset(row)

    async def find_by_id(self, asset_id: UUID) -> Asset | None:
        row = (
            (
                await self._session.execute(
                    text("SELECT * FROM collab.resource_assets WHERE asset_id=:id"),
                    {"id": asset_id},
                )
            )
            .mappings()
            .one_or_none()
        )
        return None if row is None else _to_asset(row)

    async def list_by_resource(self, resource_id: UUID) -> list[Asset]:
        rows = (
            (
                await self._session.execute(
                    text(
                        "SELECT * FROM collab.resource_assets "
                        "WHERE resource_id=:id ORDER BY created_at,asset_id"
                    ),
                    {"id": resource_id},
                )
            )
            .mappings()
            .all()
        )
        return [_to_asset(row) for row in rows]


def _to_asset(row: Any) -> Asset:
    return Asset(
        asset_id=row["asset_id"],
        resource_id=row["resource_id"],
        provider=row["provider"],
        storage_key=row["storage_key"],
        size_bytes=row["size_bytes"],
        mime=row["mime"],
        sha256=row["sha256"],
        created_by=row["created_by"],
        created_at=row["created_at"],
        original_name=row["original_name"],
    )
