from __future__ import annotations

from app_core.account.ports.idempotency_repository import (
    IdempotencyRecord,
    IdempotencyState,
)
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


class PostgresIdempotencyRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def claim(self, key: str) -> bool:
        result = await self._session.execute(
            text(
                "INSERT INTO integration.idempotency_records (idempotency_key) "
                "VALUES (:key) ON CONFLICT (idempotency_key) DO NOTHING "
                "RETURNING idempotency_key"
            ),
            {"key": key},
        )
        return result.scalar_one_or_none() is not None

    async def get(self, key: str) -> IdempotencyRecord | None:
        result = await self._session.execute(
            text(
                "SELECT response FROM integration.idempotency_records "
                "WHERE idempotency_key=:key"
            ),
            {"key": key},
        )
        row = result.scalar_one_or_none()
        if row is None:
            exists = await self._session.execute(
                text(
                    "SELECT 1 FROM integration.idempotency_records "
                    "WHERE idempotency_key=:key"
                ),
                {"key": key},
            )
            return (
                IdempotencyRecord(IdempotencyState.IN_PROGRESS)
                if exists.scalar_one_or_none() is not None
                else None
            )
        response = row.encode() if isinstance(row, str) else row
        return IdempotencyRecord(IdempotencyState.COMPLETED, response)

    async def complete(self, key: str, response: bytes) -> None:
        await self._session.execute(
            text(
                "UPDATE integration.idempotency_records SET response=:response "
                "WHERE idempotency_key=:key"
            ),
            {"key": key, "response": response.decode()},
        )

    async def delete(self, key: str) -> None:
        """Release a claim WITHOUT a stored response (a failed attempt): the
        key becomes free so the caller can retry instead of being permanently
        poisoned by an in-flight record."""
        await self._session.execute(
            text(
                "DELETE FROM integration.idempotency_records WHERE idempotency_key=:key"
            ),
            {"key": key},
        )
