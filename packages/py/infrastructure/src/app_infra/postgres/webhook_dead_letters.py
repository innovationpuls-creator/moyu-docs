"""Webhook dead-letter handling (arch 10 §deliveries): Failed webhook.deliver
tasks are the dead-letter surface; requeue replays the latest failure as a
fresh Queued task tagged ``redeliveredFrom`` (no schema change, expand-first)."""

from __future__ import annotations

import json
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

INPUT_FIELDS = (
    "task_id",
    "task_type",
    "state",
    "priority",
    "input_ref",
    "created_at",
    "queued_at",
    "schema_version",
)


class PostgresWebhookDeadLetters:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def count_failed(self, subscription_id: UUID) -> int:
        value = await self._session.scalar(
            text(
                "SELECT COUNT(*) FROM work.tasks "
                "WHERE task_type='webhook.deliver' AND state='Failed' "
                "AND input_ref::jsonb->>'subscriptionId'=:sid"
            ),
            {"sid": str(subscription_id)},
        )
        return int(value or 0)

    async def requeue_failed(self, subscription_id: UUID) -> int:
        row = (
            (
                await self._session.execute(
                    text(
                        "SELECT input_ref FROM work.tasks "
                        "WHERE task_type='webhook.deliver' AND state='Failed' "
                        "AND input_ref::jsonb->>'subscriptionId'=:sid "
                        "ORDER BY created_at DESC, task_id DESC LIMIT 1"
                    ),
                    {"sid": str(subscription_id)},
                )
            )
            .mappings()
            .first()
        )
        if row is None:
            return 0
        payload: dict[str, Any] = json.loads(row["input_ref"])
        payload["redeliveredFrom"] = "dead-letter"
        await self._session.execute(
            text(
                "INSERT INTO work.tasks "
                "(task_id,task_type,state,priority,input_ref,created_at,"
                "queued_at,schema_version) "
                "VALUES (:tid,'webhook.deliver','Queued','Background',"
                "CAST(:ref AS jsonb),now(),now(),'1.0.0')"
            ),
            {"tid": uuid4(), "ref": json.dumps(payload)},
        )
        return 1
