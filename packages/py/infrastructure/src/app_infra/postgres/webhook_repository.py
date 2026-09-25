from __future__ import annotations

from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


class PostgresWebhookSubscriptionRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def register(
        self,
        workspace_id: UUID,
        created_by: UUID,
        url: str,
        secret_key_hex: str,
    ) -> UUID:
        subscription_id = uuid4()
        await self._session.execute(
            text(
                "INSERT INTO core.webhook_subscriptions "
                "(subscription_id,workspace_id,created_by,url,secret_key_hex) "
                "VALUES (:sid,:wid,:cb,:url,:sec)"
            ),
            {
                "sid": subscription_id,
                "wid": workspace_id,
                "cb": created_by,
                "url": url,
                "sec": secret_key_hex,
            },
        )
        return subscription_id

    async def list_for_workspace(self, workspace_id: UUID) -> list[dict[str, Any]]:
        rows = (
            (
                await self._session.execute(
                    text(
                        "SELECT subscription_id,url,status,created_at "
                        "FROM core.webhook_subscriptions "
                        "WHERE workspace_id=:wid ORDER BY created_at DESC"
                    ),
                    {"wid": workspace_id},
                )
            )
            .mappings()
            .all()
        )
        return [dict(r) for r in rows]

    async def remove(self, subscription_id: UUID, workspace_id: UUID) -> bool:
        result = await self._session.execute(
            text(
                "DELETE FROM core.webhook_subscriptions "
                "WHERE subscription_id=:sid AND workspace_id=:wid"
            ),
            {"sid": subscription_id, "wid": workspace_id},
        )
        return (getattr(result, "rowcount", 0) or 0) > 0

    async def fetch_by_id(self, subscription_id: UUID) -> tuple[UUID, str, str] | None:
        """(workspace_id, url, secret) lookup for DLQ replay (arch 10)."""
        row = (
            (
                await self._session.execute(
                    text(
                        "SELECT workspace_id, url, secret_key_hex "
                        "FROM core.webhook_subscriptions "
                        "WHERE subscription_id=:sid AND status='Active'"
                    ),
                    {"sid": subscription_id},
                )
            )
            .mappings()
            .first()
        )
        if row is None:
            return None
        return (row["workspace_id"], row["url"], row["secret_key_hex"])

    async def fetch(
        self, workspace_id: UUID, subscription_id: UUID
    ) -> tuple[str, str] | None:
        row = (
            (
                await self._session.execute(
                    text(
                        "SELECT url, secret_key_hex FROM core.webhook_subscriptions "
                        "WHERE workspace_id=:wid AND subscription_id=:sid AND "
                        "status='Active'"
                    ),
                    {"wid": workspace_id, "sid": subscription_id},
                )
            )
            .mappings()
            .first()
        )
        if row is None:
            return None
        return (str(row["url"]), str(row["secret_key_hex"]))


class PostgresWebhookSubscriptionLoader:
    """Read delivery credentials in a short session closed before HTTP I/O."""

    def __init__(self, factory: async_sessionmaker[AsyncSession]) -> None:
        self._factory = factory

    async def fetch(
        self, workspace_id: UUID, subscription_id: UUID
    ) -> tuple[str, str] | None:
        async with self._factory() as session:
            async with session.begin():
                return await PostgresWebhookSubscriptionRepository(session).fetch(
                    workspace_id, subscription_id
                )
