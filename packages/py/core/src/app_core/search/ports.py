from __future__ import annotations

from typing import Protocol, Sequence
from uuid import UUID

from app_core.search.domain import SearchHit


class SearchRepository(Protocol):
    async def search_workspace(
        self,
        workspace_id: UUID,
        query: str,
        *,
        limit: int = 20,
        resource_type: str | None = None,
        since: object | None = None,
        until: object | None = None,
        author: UUID | None = None,
        project_id: UUID | None = None,
        folder_id: UUID | None = None,
    ) -> Sequence[SearchHit]: ...
    async def suggest(
        self, workspace_id: UUID, prefix: str, *, limit: int = 8
    ) -> list[str]: ...
