from __future__ import annotations

from typing import Any, Sequence
from uuid import UUID

from app_core.search.domain import SearchHit
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


class PostgresSearchRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def upsert(
        self,
        *,
        resource_id: UUID,
        workspace_id: UUID,
        project_id: UUID,
        resource_type: str,
        name: str,
        searchable_text: str,
        lifecycle: str,
    ) -> None:
        await self._session.execute(
            text(
                "INSERT INTO collab.resource_search_index "
                "(resource_id,workspace_id,project_id,resource_type,name,"
                "searchable_text,lifecycle) "
                "VALUES (:rid,:wid,:pid,:rtype,:name,:text,:lc) "
                "ON CONFLICT (resource_id) DO UPDATE SET "
                "workspace_id=EXCLUDED.workspace_id,"
                "project_id=EXCLUDED.project_id,"
                "resource_type=EXCLUDED.resource_type,"
                "name=EXCLUDED.name,"
                "searchable_text=EXCLUDED.searchable_text,"
                "lifecycle=EXCLUDED.lifecycle,"
                "updated_at=now()"
            ),
            {
                "rid": resource_id,
                "wid": workspace_id,
                "pid": project_id,
                "rtype": resource_type,
                "name": name,
                "text": searchable_text,
                "lc": lifecycle,
            },
        )

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
    ) -> Sequence[SearchHit]:
        rows = (
            (
                await self._session.execute(
                    text(
                        "SELECT s.resource_id, s.name, s.resource_type, "
                        "s.searchable_text, "
                        "GREATEST("
                        "  ts_rank(s.body_tsv, plainto_tsquery('simple', :q)),"
                        "  CASE WHEN s.name ILIKE :pat OR s.searchable_text ILIKE :pat "
                        "       THEN 0.05 ELSE 0 END"
                        ") AS score, "
                        "s.updated_at "
                        "FROM collab.resource_search_index s "
                        "WHERE s.workspace_id=:wid AND s.lifecycle='Active' "
                        "AND (s.body_tsv @@ plainto_tsquery('simple', :q) "
                        "     OR s.name ILIKE :pat OR s.searchable_text ILIKE :pat) "
                        "AND (CAST(:rtype AS text) IS NULL OR s.resource_type=:rtype) "
                        "AND (CAST(:since AS timestamptz) IS NULL "
                        "OR s.updated_at >= :since) "
                        "AND (CAST(:until AS timestamptz) IS NULL "
                        "OR s.updated_at <= :until) "
                        "AND (CAST(:pid AS uuid) IS NULL OR s.project_id=:pid) "
                        "AND (CAST(:fid AS uuid) IS NULL OR s.resource_id IN ("
                        "    SELECT res.resource_id FROM core.resources res "
                        "    WHERE res.folder_id=:fid"
                        ")) "
                        "AND (CAST(:author AS uuid) IS NULL OR s.resource_id IN ("
                        "    SELECT r.resource_id FROM core.resources r "
                        "    WHERE r.created_by=:author"
                        ")) "
                        "ORDER BY score DESC LIMIT :lim"
                    ),
                    {
                        "wid": workspace_id,
                        "q": query,
                        "pat": f"%{query}%",
                        "lim": limit,
                        "rtype": resource_type,
                        "since": since,
                        "until": until,
                        "author": author,
                        "pid": project_id,
                        "fid": folder_id,
                    },
                )
            )
            .mappings()
            .all()
        )
        return [_to_hit(r, query) for r in rows]

    async def suggest(
        self, workspace_id: UUID, prefix: str, *, limit: int = 8
    ) -> list[str]:
        rows = (
            (
                await self._session.execute(
                    text(
                        "SELECT DISTINCT name FROM collab.resource_search_index "
                        "WHERE workspace_id=:wid AND lifecycle='Active' "
                        "AND name ILIKE :prefix "
                        "ORDER BY name LIMIT :lim"
                    ),
                    {"wid": workspace_id, "prefix": f"{prefix}%", "lim": limit},
                )
            )
            .mappings()
            .all()
        )
        return [str(r["name"]) for r in rows]


def _to_hit(row: Any, query: str) -> SearchHit:
    text = str(row.get("searchable_text") or "")
    lower = text.lower()
    position = lower.find(query.lower())
    if position < 0:
        snippet = None
    else:
        start = max(0, position - 24)
        end = min(len(text), position + len(query) + 36)
        snippet = text[start:end]
    return SearchHit(
        resource_id=row["resource_id"],
        name=row["name"],
        resource_type=row["resource_type"],
        score=float(row["score"] or 0.0),
        snippet=snippet,
        updated_at=row["updated_at"],
    )
