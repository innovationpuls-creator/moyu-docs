"""Guarded proof: the maintenance sweep purges only the aged Failed
webhook.deliver rows (arch 10 §DLQ retention)."""

from __future__ import annotations

import json
from uuid import UUID, uuid4

import pytest
from app_infra.postgres.engine import engine
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


@pytest.mark.asyncio
async def test_retention_removes_only_aged_failed_rows() -> None:
    connection = await engine.connect()
    session = AsyncSession(connection)
    try:
        sub_id = str(uuid4())
        workspace_id = str(uuid4())
        existing_aged_failed = await session.scalar(
            text(
                "SELECT count(*) FROM work.tasks WHERE "
                "task_type='webhook.deliver' AND state='Failed' AND "
                "created_at < now() - interval '14 days'"
            )
        )
        if existing_aged_failed:
            pytest.skip("retention deletes all aged deliveries; matching rows exist")
        await session.rollback()
        task_ids: dict[str, list[UUID]] = {"Failed": [], "Queued": [], "Running": []}
        transaction = await session.begin()
        try:
            for age_days, state in (
                (20, "Failed"),
                (3, "Failed"),
                (3, "Queued"),
                (3, "Running"),
            ):
                task_id = uuid4()
                task_ids[state].append(task_id)
                await session.execute(
                    text(
                        "INSERT INTO work.tasks "
                        "(task_id,task_type,state,priority,input_ref,created_at,"
                        "queued_at,schema_version) "
                        "VALUES (:t,'webhook.deliver',:s,'Background',CAST(:r AS "
                        "jsonb),now()-CAST(:d AS interval),now(),'1.0.0')"
                    ),
                    {
                        "t": task_id,
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
            from app_infra.postgres.webhook_retention import PostgresWebhookRetention

            removed = await PostgresWebhookRetention(session).run()
            assert removed >= 1
            states = (
                (
                    await session.execute(
                        text(
                            "SELECT task_id,state FROM work.tasks WHERE task_id IN "
                            "(:failed_old,:failed_recent,:queued,:running)"
                        ),
                        {
                            "failed_old": task_ids["Failed"][0],
                            "failed_recent": task_ids["Failed"][1],
                            "queued": task_ids["Queued"][0],
                            "running": task_ids["Running"][0],
                        },
                    )
                )
                .mappings()
                .all()
            )
            assert {row["task_id"]: row["state"] for row in states} == {
                task_ids["Failed"][1]: "Failed",
                task_ids["Queued"][0]: "Queued",
                task_ids["Running"][0]: "Running",
            }
        finally:
            await transaction.rollback()
    finally:
        await session.close()
        await connection.close()
