from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID


class SearchError(Exception):
    pass


@dataclass(frozen=True)
class SearchHit:
    resource_id: UUID
    name: str
    resource_type: str
    score: float
    snippet: str | None = None
    updated_at: datetime | None = None
