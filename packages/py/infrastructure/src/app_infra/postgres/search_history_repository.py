from __future__ import annotations

from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


class PostgresSearchHistoryRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def record(self, account_id: UUID, query: str) -> None:
        await self._session.execute(
            text(
                "INSERT INTO core.search_history "
                "(history_id,account_id,query) VALUES (:hid,:aid,:q) "
                "ON CONFLICT (account_id,query) DO UPDATE SET created_at=now()"
            ),
            {"hid": uuid4(), "aid": account_id, "q": query[:200]},
        )

    async def list_for_account(
        self, account_id: UUID, *, limit: int = 20
    ) -> list[tuple[str, Any]]:
        rows = (
            (
                await self._session.execute(
                    text(
                        "SELECT query, created_at FROM core.search_history "
                        "WHERE account_id=:aid ORDER BY created_at DESC LIMIT :lim"
                    ),
                    {"aid": account_id, "lim": limit},
                )
            )
            .mappings()
            .all()
        )
        return [(r["query"], r["created_at"]) for r in rows]

    async def clear_for_account(self, account_id: UUID) -> int:
        result = await self._session.execute(
            text("DELETE FROM core.search_history WHERE account_id=:aid"),
            {"aid": account_id},
        )
        return getattr(result, "rowcount", 0) or 0
