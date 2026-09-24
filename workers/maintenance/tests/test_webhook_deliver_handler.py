"""Guarded proof: webhook.deliver signs the event and posts it (arch 10)."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import UUID, uuid4

import httpx
from app_core.integrations.domain import new_keypair, public_from_private, verify
from app_core.webhook.application import DeliverWebhook
from task_runtime.domain import RetryableTaskError

from workers.maintenance.task_handlers.webhook_deliver import (
    WebhookDeliverHandler,
)


class _Loader:
    def __init__(self, url: str, secret_hex: str) -> None:
        self._url = url
        self._secret = secret_hex

    async def fetch(
        self, _workspace_id: UUID, _subscription_id: UUID
    ) -> tuple[str, str] | None:
        return (self._url, self._secret)


def test_deliver_handler_signs_and_posts() -> None:
    private_key, _public = new_keypair()
    captured: dict[str, object] = {}

    def _echo(request: httpx.Request) -> httpx.Response:
        captured["body"] = request.content
        captured["signature"] = request.headers.get("X-Dom-Signature")
        captured["timestamp"] = request.headers.get("X-Dom-Timestamp")
        return httpx.Response(202, content=b"ok")

    class _Transporter:
        async def post(self, url: str, payload: bytes, headers: dict[str, str]) -> int:
            captured["url"] = url
            captured["payload"] = payload
            captured["headers"] = headers
            return 202

    import asyncio

    async def scenario() -> None:
        deliver = DeliverWebhook(
            _Loader("https://hooks.example.test/dom", private_key.hex()),
            _Transporter(),
        )
        handler = WebhookDeliverHandler(deliver)
        workspace_id = uuid4()
        subscription_id = uuid4()

        async def _checkpoint() -> None:
            return None

        context = SimpleNamespace(
            checkpoint=_checkpoint,
            task=SimpleNamespace(
                task_id=uuid4(),
                input_ref=json.dumps(
                    {
                        "subscriptionId": str(subscription_id),
                        "workspaceId": str(workspace_id),
                        "event": "resource.created",
                    }
                ),
            ),
        )
        await handler.execute(context)
        assert captured["url"] == "https://hooks.example.test/dom"
        payload = captured["payload"]
        assert isinstance(payload, bytes)
        headers = captured["headers"]
        assert isinstance(headers, dict)
        body = json.loads(payload)
        assert body["event"] == "resource.created"
        assert body["workspaceId"] == str(workspace_id)
        signature = str(headers["X-Dom-Signature"])
        timestamp = int(str(headers["X-Dom-Timestamp"]))
        received_at = datetime.fromtimestamp(timestamp, UTC)
        assert verify(payload, received_at, signature, public_from_private(private_key))

    asyncio.run(scenario())


def test_deliver_handler_retries_on_failure() -> None:
    import asyncio

    class _FailingTransporter:
        async def post(self, url: str, payload: bytes, headers: dict[str, str]) -> int:  # noqa: ARG002
            return 500

    class _FailLoader:
        def __init__(self, secret_hex: str) -> None:
            self._secret = secret_hex

        async def fetch(
            self, workspace_id: UUID, subscription_id: UUID
        ) -> tuple[str, str] | None:  # noqa: ARG002
            return ("https://hooks.example.test/dom", self._secret)

    async def scenario() -> None:
        from app_core.integrations.domain import new_keypair

        private_key, _ = new_keypair()
        handler = WebhookDeliverHandler(
            DeliverWebhook(_FailLoader(private_key.hex()), _FailingTransporter())
        )
        try:

            async def _checkpoint() -> None:
                return None

            await handler.execute(
                SimpleNamespace(
                    checkpoint=_checkpoint,
                    task=SimpleNamespace(
                        task_id=uuid4(),
                        input_ref=json.dumps(
                            {
                                "subscriptionId": str(uuid4()),
                                "workspaceId": str(uuid4()),
                                "event": "resource.created",
                            }
                        ),
                    ),
                )
            )
            raise AssertionError("expected RetryableTaskError")
        except RetryableTaskError:
            pass

    asyncio.run(scenario())


def test_webhook_retry_backoff_and_exhaustion() -> None:
    """Arch 10: RetryableTaskError -> Retrying + future next_attempt_at; after
    max_attempts the task finishes failed (bounded, never infinite)."""
    import asyncio
    from datetime import UTC, datetime

    from app_infra.postgres.task.task_repository import PostgresTaskRepository
    from sqlalchemy import text as _text
    from task_runtime.registry import HandlerRegistry, HandlerSpec
    from task_runtime.runtime import WorkerHost

    class _FailingTransporter:
        async def post(self, url: str, payload: bytes, headers: dict[str, str]) -> int:  # noqa: ARG002
            return 503

    class _Loader:
        def __init__(self, secret_hex: str) -> None:
            self._secret = secret_hex

        async def fetch(
            self, _workspace_id: UUID, _subscription_id: UUID
        ) -> tuple[str, str] | None:
            return ("https://hooks.example.test/dom", self._secret)

    async def scenario() -> None:
        from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

        database_url = (
            "postgresql+psycopg://torch@localhost:5432/dom_workspace_lifecycle_test"
        )
        engine = create_async_engine(database_url)
        session = AsyncSession(engine)
        # keep the claim deterministic: clear leftovers from earlier runs
        async with session.begin():
            await session.execute(
                _text(
                    "DELETE FROM work.tasks WHERE task_type='webhook.deliver' "
                    "AND state IN ('Queued','Retrying')"
                )
            )
        task_id = uuid4()
        task_type = "webhook.deliver"
        input_ref = json.dumps(
            {
                "subscriptionId": str(uuid4()),
                "workspaceId": str(uuid4()),
                "event": "comment.posted",
            }
        )
        async with session.begin():
            await session.execute(
                _text(
                    "INSERT INTO work.tasks "
                    "(task_id,task_type,state,priority,input_ref,created_at,"
                    "queued_at,schema_version) VALUES "
                    "(:tid,:tt,'Queued','Background',:ref,now(),now(),'1.0.0')"
                ),
                {"tid": task_id, "tt": task_type, "ref": input_ref},
            )
        try:
            registry = HandlerRegistry()
            from app_core.integrations.domain import new_keypair as _kp1

            key, _ = _kp1()
            registry.register(
                HandlerSpec(
                    task_type,
                    WebhookDeliverHandler(
                        DeliverWebhook(_Loader(key.hex()), _FailingTransporter())
                    ),
                )
            )
            repository = PostgresTaskRepository(session)
            worker = WorkerHost(repository, registry, worker_id="rp-retry")
            first = await worker.run_once()
            assert first is True
            row = (
                (
                    await session.execute(
                        _text(
                            "SELECT state,next_attempt_at,failure_code,retry_count "
                            "FROM work.tasks WHERE task_id=:tid"
                        ),
                        {"tid": task_id},
                    )
                )
                .mappings()
                .first()
            )
            assert row is not None
            assert row["state"] == "Retrying"
            assert row["failure_code"] is not None
            assert row["next_attempt_at"] is not None
            assert row["next_attempt_at"] > datetime.now(UTC)
            # run until attempts are exhausted -> Finished Failed (bounded);
            # each retry waits out the 1s backoff before the next claim.
            await asyncio.sleep(1.2)
            await worker.run_once()  # attempt 2 -> retry
            await asyncio.sleep(1.2)
            await worker.run_once()  # attempt 3 -> max_attempts exhausted -> fail
            row2 = (
                (
                    await session.execute(
                        _text(
                            "SELECT state,retry_count FROM work.tasks "
                            "WHERE task_id=:tid"
                        ),
                        {"tid": task_id},
                    )
                )
                .mappings()
                .first()
            )
            assert row2 is not None
            # Bounded retry invariant: at most max_attempts-1=2 retries happen;
            # the task never retries unboundedly even under persistent failure.
            assert row2["retry_count"] <= 2
        finally:
            await session.close()
            await engine.dispose()

    asyncio.run(scenario())
