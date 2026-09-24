from __future__ import annotations

from typing import Any
from uuid import UUID, uuid4

from app_core.integrations.domain import IntegrationKey
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


class PostgresIntegrationKeyRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(
        self,
        *,
        account_id: UUID,
        label: str,
        public_key_hex: str,
    ) -> IntegrationKey:
        key_id = uuid4()
        row = (
            (
                await self._session.execute(
                    text(
                        "INSERT INTO core.integration_keys "
                        "(key_id,account_id,label,public_key_hex) "
                        "VALUES (:kid,:aid,:label,:pub) RETURNING *"
                    ),
                    {
                        "kid": key_id,
                        "aid": account_id,
                        "label": label,
                        "pub": public_key_hex,
                    },
                )
            )
            .mappings()
            .one()
        )
        return _to_key(row)

    async def find_by_id(self, key_id: UUID) -> IntegrationKey | None:
        row = (
            (
                await self._session.execute(
                    text("SELECT * FROM core.integration_keys WHERE key_id=:id"),
                    {"id": key_id},
                )
            )
            .mappings()
            .one_or_none()
        )
        return None if row is None else _to_key(row)

    async def public_key_hex(self, key_id: UUID) -> str | None:
        return await self._session.scalar(
            text("SELECT public_key_hex FROM core.integration_keys WHERE key_id=:id"),
            {"id": key_id},
        )

    async def revoke(self, key_id: UUID) -> None:
        await self._session.execute(
            text("UPDATE core.integration_keys SET revoked=TRUE WHERE key_id=:id"),
            {"id": key_id},
        )


def _to_key(row: Any) -> IntegrationKey:
    return IntegrationKey(
        key_id=row["key_id"],
        account_id=row["account_id"],
        label=row["label"],
        created_at=row["created_at"],
        revoked=row["revoked"],
    )
