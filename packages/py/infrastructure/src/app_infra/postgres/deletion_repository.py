from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


class PostgresDeletionRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def schedule(self, account_id: UUID, execute_after: datetime) -> None:
        await self._session.execute(
            text(
                "INSERT INTO auth.account_deletion_requests "
                "(account_id, state, requested_at, execute_after) "
                "VALUES (:account_id, 'Pending', now(), :execute_after) "
                "ON CONFLICT (account_id) DO UPDATE SET "
                "state='Pending', execute_after=EXCLUDED.execute_after, "
                "cancelled_at=NULL, completed_at=NULL "
                "WHERE auth.account_deletion_requests.state='Cancelled'"
            ),
            {"account_id": account_id, "execute_after": execute_after},
        )

    async def cancel(self, account_id: UUID, at: datetime) -> bool:
        result = await self._session.execute(
            text(
                "UPDATE auth.account_deletion_requests "
                "SET state='Cancelled', cancelled_at=:at "
                "WHERE account_id=:account_id AND state='Pending' "
                "RETURNING account_id"
            ),
            {"account_id": account_id, "at": at},
        )
        return result.scalar_one_or_none() is not None

    async def complete(self, account_id: UUID, at: datetime) -> bool:
        result = await self._session.execute(
            text(
                "UPDATE auth.account_deletion_requests SET state='Completed', "
                "completed_at=:at WHERE account_id=:account_id AND state='Pending' "
                "AND execute_after <= :at RETURNING account_id"
            ),
            {"account_id": account_id, "at": at},
        )
        return result.scalar_one_or_none() is not None
