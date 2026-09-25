from __future__ import annotations

import json
from collections.abc import Awaitable, Callable
from datetime import datetime
from typing import Any
from uuid import UUID

from app_core.assets.domain import Asset
from app_core.common.exceptions import IdempotencyConflictError
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

_KEY_PREFIX = "asset:upload:"


class PostgresAssetUploadIdempotencyRepository:
    """Fingerprint-bound Asset upload replay using the existing shared table."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def execute(
        self,
        key: str,
        request_fingerprint: str,
        operation: Callable[[], Awaitable[Asset]],
    ) -> Asset:
        storage_key = f"{_KEY_PREFIX}{key}"
        claimed = await self._session.scalar(
            text(
                "INSERT INTO integration.idempotency_records "
                "(idempotency_key, response) VALUES (:key, :response) "
                "ON CONFLICT (idempotency_key) DO NOTHING "
                "RETURNING idempotency_key"
            ),
            {
                "key": storage_key,
                "response": json.dumps(
                    {
                        "request_fingerprint": request_fingerprint,
                        "phase": "in_progress",
                    },
                    separators=(",", ":"),
                ),
            },
        )
        if claimed is not None:
            asset = await operation()
            await self._session.execute(
                text(
                    "UPDATE integration.idempotency_records SET response=:response "
                    "WHERE idempotency_key=:key"
                ),
                {
                    "key": storage_key,
                    "response": json.dumps(
                        {
                            "request_fingerprint": request_fingerprint,
                            "phase": "completed",
                            "asset": _encode_asset(asset),
                        },
                        separators=(",", ":"),
                    ),
                },
            )
            return asset

        stored = await self._session.scalar(
            text(
                "SELECT response FROM integration.idempotency_records "
                "WHERE idempotency_key=:key"
            ),
            {"key": storage_key},
        )
        if stored is None:
            raise _conflict("Idempotency key is already in progress.")
        envelope = json.loads(stored)
        if envelope.get("request_fingerprint") != request_fingerprint:
            raise _conflict("Idempotency key was used for a different upload.")
        if envelope.get("phase") != "completed":
            raise _conflict("Idempotency key is already in progress.")
        return _decode_asset(envelope["asset"])


def _conflict(message: str) -> IdempotencyConflictError:
    return IdempotencyConflictError(message, "IDEMPOTENCY_KEY_CONFLICT")


def _encode_asset(asset: Asset) -> dict[str, Any]:
    return {
        "assetId": str(asset.asset_id),
        "resourceId": str(asset.resource_id),
        "provider": asset.provider,
        "storageKey": asset.storage_key,
        "sizeBytes": asset.size_bytes,
        "mime": asset.mime,
        "sha256": asset.sha256,
        "createdBy": str(asset.created_by) if asset.created_by is not None else None,
        "createdAt": asset.created_at.isoformat() if asset.created_at else None,
        "originalName": asset.original_name,
    }


def _decode_asset(payload: dict[str, Any]) -> Asset:
    created_at = payload["createdAt"]
    return Asset(
        asset_id=UUID(payload["assetId"]),
        resource_id=UUID(payload["resourceId"]),
        provider=payload["provider"],
        storage_key=payload["storageKey"],
        size_bytes=payload["sizeBytes"],
        mime=payload["mime"],
        sha256=payload["sha256"],
        created_by=UUID(payload["createdBy"])
        if payload["createdBy"] is not None
        else None,
        created_at=datetime.fromisoformat(created_at) if created_at else None,
        original_name=payload["originalName"],
    )
