"""Guarded proof: the maintenance sweep purges only the aged Failed
webhook.deliver rows (arch 10 §DLQ retention)."""

from __future__ import annotations

import json
from uuid import uuid4

import pytest
from app_infra.postgres.engine import engine
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


async def _count(session: AsyncSession, state: str) -> int:
    return int(
        await session.scalar(
            text(
                "SELECT COUNT(*) FROM work.tasks "
                "WHERE task_type='webhook.deliver' AND state=:s"
            ),
            {"s": state},
        )
        or 0
    )


@pytest.mark.asyncio
async def test_sweep_retains_only_within_window() -> None:
    connection = await engine.connect()
    session = AsyncSession(connection)
    try:
        sub_id = str(uuid4())
        workspace_id = str(uuid4())
        async with session.begin():
            await session.execute(
                text("DELETE FROM work.tasks WHERE task_type='webhook.deliver'")
            )
            for age_days, state in (
                (20, "Failed"),
                (3, "Failed"),
                (3, "Queued"),
                (3, "Running"),
            ):
                await session.execute(
                    text(
                        "INSERT INTO work.tasks "
                        "(task_id,task_type,state,priority,input_ref,created_at,"
                        "queued_at,schema_version) "
                        "VALUES (:t,'webhook.deliver',:s,'Background',CAST(:r AS "
                        "jsonb),now()-CAST(:d AS interval),now(),'1.0.0')"
                    ),
                    {
                        "t": uuid4(),
                        "s": state,
                        "r": json.dumps(
                            {
                                "subscriptionId": sub_id,
                                "workspaceId": workspace_id,
                                "event": "comment.posted",
                            }
                        ),
                        "d": f"{age_days} days",
                    },
                )
        from workers.maintenance.main import sweep

        removed = await sweep(session)
        # the sweep enqueues checkpoint/purge work too; the retention contract
        # is the POST-state: only the aged Failed row left the DL surface
        assert removed >= 1
        assert await _count(session, "Failed") == 1
        assert await _count(session, "Queued") == 1
        assert await _count(session, "Running") == 1
    finally:
        await session.close()
        await connection.close()
