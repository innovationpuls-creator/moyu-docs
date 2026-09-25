from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import cast
from uuid import uuid4

import pytest
from app_core.import_export.ports import TemporaryAssetStore
from app_core.webhook.application import DeliverWebhook
from app_core.webhook.domain import WebhookEvent
from app_infra.postgres.webhook_repository import (
    PostgresWebhookSubscriptionLoader,
    PostgresWebhookSubscriptionRepository,
)
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from workers.maintenance.main import (
    _ExecutionTransaction,
    _TransactionReleasingTemporaryAssetStore,
    _TransactionReleasingWebhookTransporter,
)


class _Transaction:
    def __init__(self, session: _Session, events: list[str]) -> None:
        self._session = session
        self._events = events
        self.is_active = True

    def __await__(self):
        async def started():
            return self

        return started().__await__()

    async def __aenter__(self) -> _Transaction:
        return self

    async def __aexit__(self, exc_type, exc, traceback) -> None:
        if exc_type is None:
            await self.commit()
        else:
            await self.rollback()

    async def commit(self) -> None:
        self._events.append("commit")
        self.is_active = False
        self._session.transaction_active = False

    async def rollback(self) -> None:
        self._events.append("rollback")
        self.is_active = False
        self._session.transaction_active = False


class _Session:
    def __init__(self, events: list[str]) -> None:
        self.events = events
        self.transaction_active = False

    def begin(self) -> _Transaction:
        self.events.append("begin")
        self.transaction_active = True
        return _Transaction(self, self.events)


class _SessionFactory:
    def __init__(self) -> None:
        self.events: list[str] = []
        self.session = _Session(self.events)
        self.session_open = False

    def __call__(self):
        return self._session_scope()

    @asynccontextmanager
    async def _session_scope(self):
        self.session_open = True
        try:
            yield self.session
        finally:
            self.session_open = False


@pytest.mark.asyncio
async def test_webhook_loader_closes_short_session_before_returning(monkeypatch):
    factory = _SessionFactory()
    workspace_id = uuid4()
    subscription_id = uuid4()

    async def fetch(repository, requested_workspace, requested_subscription):
        assert factory.session_open
        assert repository._session.transaction_active
        assert requested_workspace == workspace_id
        assert requested_subscription == subscription_id
        return "https://hooks.example.test", "secret"

    monkeypatch.setattr(PostgresWebhookSubscriptionRepository, "fetch", fetch)
    loader = PostgresWebhookSubscriptionLoader(
        cast(async_sessionmaker[AsyncSession], factory)
    )

    result = await loader.fetch(workspace_id, subscription_id)

    assert result == ("https://hooks.example.test", "secret")
    assert not factory.session_open
    assert not factory.session.transaction_active


@pytest.mark.asyncio
async def test_webhook_post_runs_after_execution_transaction_is_released():
    events: list[str] = []
    session = _Session(events)
    transaction = _ExecutionTransaction(cast(AsyncSession, session))

    class _Transporter:
        async def post(self, url: str, payload: bytes, headers: dict[str, str]) -> int:
            assert not session.transaction_active
            events.append("http.post")
            return 202

    await transaction.begin()
    transporter = _TransactionReleasingWebhookTransporter(_Transporter(), transaction)
    response = await transporter.post("https://hooks.example.test", b"{}", {})
    await transaction.commit()

    assert response == 202
    assert events == ["begin", "commit", "http.post", "begin", "commit"]


@pytest.mark.asyncio
async def test_webhook_post_resumes_execution_transaction_after_transport_error():
    events: list[str] = []
    session = _Session(events)
    transaction = _ExecutionTransaction(cast(AsyncSession, session))

    class _FailingTransporter:
        async def post(self, url: str, payload: bytes, headers: dict[str, str]) -> int:
            assert not session.transaction_active
            events.append("http.error")
            raise TimeoutError("transport timeout")

    await transaction.begin()
    transporter = _TransactionReleasingWebhookTransporter(
        _FailingTransporter(), transaction
    )
    with pytest.raises(TimeoutError):
        await transporter.post("https://hooks.example.test", b"{}", {})

    assert session.transaction_active
    await transaction.rollback()
    assert events == ["begin", "commit", "http.error", "begin", "rollback"]


@pytest.mark.asyncio
async def test_temporary_asset_io_releases_execution_transaction():
    events: list[str] = []
    session = _Session(events)
    transaction = _ExecutionTransaction(cast(AsyncSession, session))

    class _Assets:
        async def get_import_source(self, asset_id):
            assert not session.transaction_active
            events.append(f"asset.get:{asset_id}")
            return b"source"

    await transaction.begin()
    assets = _TransactionReleasingTemporaryAssetStore(
        cast(TemporaryAssetStore, _Assets()), transaction
    )
    asset_id = uuid4()

    assert await assets.get_import_source(asset_id) == b"source"
    assert session.transaction_active
    await transaction.commit()

    assert events == ["begin", "commit", f"asset.get:{asset_id}", "begin", "commit"]


@pytest.mark.asyncio
async def test_delivery_loads_then_releases_both_sessions_before_http(monkeypatch):
    events: list[str] = []
    factory = _SessionFactory()
    factory.events = events
    factory.session.events = events
    execution_session = _Session(events)
    transaction = _ExecutionTransaction(cast(AsyncSession, execution_session))
    workspace_id = uuid4()
    subscription_id = uuid4()

    async def fetch(repository, requested_workspace, requested_subscription):
        assert factory.session_open
        assert repository._session.transaction_active
        assert requested_workspace == workspace_id
        assert requested_subscription == subscription_id
        events.append("subscription.read")
        return "https://hooks.example.test", "01" * 32

    class _Transporter:
        async def post(self, url: str, payload: bytes, headers: dict[str, str]) -> int:
            assert not factory.session_open
            assert not execution_session.transaction_active
            events.append("http.post")
            return 202

    monkeypatch.setattr(PostgresWebhookSubscriptionRepository, "fetch", fetch)
    await transaction.begin()
    deliver = DeliverWebhook(
        PostgresWebhookSubscriptionLoader(
            cast(async_sessionmaker[AsyncSession], factory)
        ),
        _TransactionReleasingWebhookTransporter(_Transporter(), transaction),
    )

    result = await deliver.execute(
        workspace_id,
        subscription_id,
        WebhookEvent("resource.created", str(workspace_id), datetime.now(UTC)),
    )
    await transaction.commit()

    assert result.delivered
    assert events == [
        "begin",
        "begin",
        "subscription.read",
        "commit",
        "commit",
        "http.post",
        "begin",
        "commit",
    ]
