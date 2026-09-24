from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID


class AssetError(Exception):
    pass


@dataclass(frozen=True)
class Asset:
    asset_id: UUID
    resource_id: UUID
    provider: str
    storage_key: str
    size_bytes: int
    mime: str | None
    sha256: str
    created_by: UUID | None
    created_at: datetime | None = None
