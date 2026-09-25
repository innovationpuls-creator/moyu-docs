from __future__ import annotations

from contextlib import asynccontextmanager
from decimal import Decimal
from typing import cast
from uuid import uuid4

import pytest
from app_infra.postgres.task.task_repository import PostgresTaskRepository
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from workers.maintenance.main import _TransactionalTaskRepository


class _Session:
    def __init__(self) -> None:
        self.transaction_active = False

    @asynccontextmanager
    async def begin(self):
        self.transaction_active = True
        try:
            yield self
        finally:
            self.transaction_active = False


class _SessionFactory:
    def __init__(self, session: _Session) -> None:
        self.session = session

    def __call__(self):
        return self._session_scope()

    @asynccontextmanager
    async def _session_scope(self):
        yield self.session


@pytest.mark.asyncio
async def test_progress_update_uses_a_short_control_transaction(monkeypatch) -> None:
    session = _Session()
    calls = []

    async def update_progress(repository, *args, **kwargs):
        assert session.transaction_active
        calls.append((args, kwargs))

    monkeypatch.setattr(PostgresTaskRepository, "update_progress", update_progress)
    repository = _TransactionalTaskRepository(
        cast(async_sessionmaker[AsyncSession], _SessionFactory(session))
    )
    task_id = uuid4()
    attempt_id = uuid4()

    await repository.update_progress(
        task_id,
        attempt_id,
        4,
        stage="replaying",
        message_code="history.restore.replaying",
        current=1,
        total=3,
        percentage=Decimal("33.33"),
    )

    assert not session.transaction_active
    assert calls == [
        (
            (task_id, attempt_id, 4),
            {
                "stage": "replaying",
                "message_code": "history.restore.replaying",
                "current": 1,
                "total": 3,
                "percentage": Decimal("33.33"),
            },
        )
    ]
