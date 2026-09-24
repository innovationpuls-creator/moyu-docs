from __future__ import annotations

from uuid import UUID

from app_core.search.domain import SearchHit
from app_core.search.ports import SearchRepository


class SearchWorkspace:
    """Arch 11 §6: workspace-scoped name + body search (member authority is
    enforced by the caller via the Permission membership check)."""

    def __init__(self, search: SearchRepository) -> None:
        self._search = search

    async def execute(
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
    ) -> list[SearchHit]:
        if not query.strip():
            return []
        hits = await self._search.search_workspace(
            workspace_id,
            query,
            limit=limit,
            resource_type=resource_type,
            since=since,
            until=until,
            author=author,
            project_id=project_id,
            folder_id=folder_id,
        )
        return [h for h in hits if h.score > 0]


class SuggestSearches:
    """Arch 11 §3: prefix suggestions from the workspace corpus."""

    def __init__(self, search: SearchRepository) -> None:
        self._search = search

    async def execute(self, workspace_id: UUID, prefix: str) -> list[str]:
        if not prefix.strip():
            return []
        return await self._search.suggest(workspace_id, prefix)
