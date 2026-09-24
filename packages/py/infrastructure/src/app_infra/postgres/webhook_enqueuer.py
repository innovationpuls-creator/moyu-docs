"""Enqueue webhook.deliver tasks for every Active subscription (arch 10)."""

from __future__ import annotations

import json
from collections.abc import Sequence
from datetime import datetime, timezone
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

TASK_TYPE = "webhook.deliver"

_NOW = datetime.now(timezone.utc)


def webhook_input(workspace_id: UUID, subscription_id: UUID, event: str) -> str:
    return json.dumps(
        {
            "subscriptionId": str(subscription_id),
            "workspaceId": str(workspace_id),
            "event": event,
        },
        separators=(",", ":"),
    )


async def _insert_tasks(
    session: AsyncSession,
    rows: Sequence[Any],
    workspace_id: UUID,
    event: str,
) -> int:
    for row in rows:
        subscription_id = UUID(str(row["subscription_id"]))
        await session.execute(
            text(
                "INSERT INTO work.tasks "
                "(task_id,task_type,state,priority,input_ref,created_at,"
                "queued_at,schema_version) VALUES "
                "(:task_id,:task_type,'Queued','Background',"
                ":input_ref,:now,:now,'1.0.0') ON CONFLICT (task_id) DO NOTHING"
            ),
            {
                "task_id": uuid4(),
                "task_type": TASK_TYPE,
                "input_ref": webhook_input(workspace_id, subscription_id, event),
                "now": _NOW,
            },
        )
    return len(rows)


async def enqueue_webhook_events(
    session: AsyncSession, workspace_id: UUID, event: str
) -> int:
    rows = (
        (
            await session.execute(
                text(
                    "SELECT subscription_id, workspace_id "
                    "FROM core.webhook_subscriptions "
                    "WHERE workspace_id=:wid AND status='Active'"
                ),
                {"wid": workspace_id},
            )
        )
        .mappings()
        .all()
    )
    return await _insert_tasks(session, rows, workspace_id, event)


async def enqueue_webhook_events_for_resource(
    session: AsyncSession, resource_id: UUID, event: str
) -> int:
    """Resolve resource -> project -> workspace, then enqueue."""
    rows = (
        (
            await session.execute(
                text(
                    "SELECT ws.subscription_id, ws.workspace_id "
                    "FROM core.resources r "
                    "JOIN core.projects p ON p.project_id=r.project_id "
                    "JOIN core.webhook_subscriptions ws "
                    "ON ws.workspace_id=p.workspace_id AND ws.status='Active' "
                    "WHERE r.resource_id=:rid"
                ),
                {"rid": resource_id},
            )
        )
        .mappings()
        .all()
    )
    if not rows:
        return 0
    workspace_id = UUID(str(rows[0]["workspace_id"]))
    return await _insert_tasks(session, rows, workspace_id, event)
