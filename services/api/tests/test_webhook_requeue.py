"""Guarded proof: webhook dead-letter requeue (arch 10)."""

from __future__ import annotations

import json
from types import SimpleNamespace
from uuid import uuid4

import pytest
from api.dependencies.auth import get_current_session
from api.infra.broadcast import get_broadcast_publisher
from app_infra.postgres.engine import engine
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


@pytest.mark.asyncio
async def test_requeue_failed_webhook_delivery() -> None:
    connection = await engine.connect()
    session = AsyncSession(connection)
    try:
        owner = uuid4()
        workspace_id = uuid4()
        subscription_id = uuid4()
        async with session.begin():
            await session.execute(
                text(
                    "DELETE FROM work.tasks WHERE task_type='webhook.deliver' "
                    "AND input_ref::jsonb->>'subscriptionId'=:sid"
                ),
                {"sid": str(subscription_id)},
            )
            for a, tag in ((owner, "dl"), (uuid4(), "dl2")):
                await session.execute(
                    text(
                        "INSERT INTO auth.accounts "
                        "(account_id,status,primary_email,normalized_email) "
                        "VALUES (:a,'Active',:e,:e)"
                    ),
                    {"a": a, "e": f"{tag}-{a}@test"},
                )
            await session.execute(
                text(
                    "INSERT INTO core.workspaces "
                    "(workspace_id,name,status,created_by,created_at,updated_at) "
                    "VALUES (:w,'S','Active',:a,now(),now())"
                ),
                {"w": workspace_id, "a": owner},
            )
            await session.execute(
                text(
                    "INSERT INTO core.workspace_members "
                    "(workspace_id,account_id,membership_kind) "
                    "VALUES (:w,:a,'Owner')"
                ),
                {"w": workspace_id, "a": owner},
            )
            await session.execute(
                text(
                    "INSERT INTO core.webhook_subscriptions "
                    "(subscription_id,workspace_id,url,secret_key_hex,status,"
                    "created_by,created_at) "
                    "VALUES (:s,:w,'https://hooks.test/x',:h,'Active',:a,now())"
                ),
                {
                    "s": subscription_id,
                    "w": workspace_id,
                    "h": "00" * 32,
                    "a": owner,
                },
            )

            async def insert_failed(ref: str, age_seconds: int):
                await session.execute(
                    text(
                        "INSERT INTO work.tasks "
                        "(task_id,task_type,state,priority,input_ref,created_at,"
                        "queued_at,schema_version) "
                        "VALUES (:t,'webhook.deliver','Failed','Background',"
                        "CAST(:r AS jsonb),now()-CAST(:age AS interval),"
                        "now(),'1.0.0')"
                    ),
                    {
                        "t": uuid4(),
                        "age": f"{age_seconds} seconds",
                        "r": json.dumps(
                            {
                                "subscriptionId": str(subscription_id),
                                "workspaceId": str(workspace_id),
                                "event": "comment.posted",
                                "ref": ref,
                            }
                        ),
                    },
                )

            await insert_failed("oldest", 120)
            await insert_failed("newest", 30)
        from api.main import create_app

        class _StubPublisher:
            async def publish(self, *_args, **_kwargs):
                return "stub"

        app = create_app(debug=True)
        app.dependency_overrides[get_current_session] = lambda: SimpleNamespace(
            account_id=owner
        )
        app.dependency_overrides[get_broadcast_publisher] = lambda: _StubPublisher()
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.post(
                f"/v1/webhooks/{subscription_id}/deliveries/requeue",
                json={},
            )
            assert response.status_code == 200, response.text
            body = response.json()
            assert body["requeued"] == 1
            # the DL history stays: Failed rows are never deleted, so both
            # failures remain visible after the replay
            assert body["remainingFailed"] == 2
        queued = (
            await session.execute(
                text(
                    "SELECT input_ref FROM work.tasks WHERE "
                    "task_type='webhook.deliver' AND state='Queued' AND "
                    "input_ref::jsonb->>'redeliveredFrom'='dead-letter' AND "
                    "input_ref::jsonb->>'subscriptionId'=:sid"
                ),
                {"sid": str(subscription_id)},
            )
        ).scalar()
        assert queued is not None
        payload = json.loads(queued)
        assert payload["ref"] == "newest"
        assert payload["subscriptionId"] == str(subscription_id)
    finally:
        await session.close()
        await connection.close()
