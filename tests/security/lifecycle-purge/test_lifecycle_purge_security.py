from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

import pytest
from app_core.operations.task.domain import StaleAttemptError
from app_core.workspace.application.purge import PurgeWorkspace
from app_core.workspace.ports.purge import PurgeCandidate, PurgeDisposition

from workers.maintenance.task_handlers.lifecycle_purge import (
    LifecyclePurgeHandler,
    _Context,
)


class Effects:
    async def record_effect(self, *args, **kwargs):
        raise StaleAttemptError("stale attempt")


class Purge:
    def __init__(self, candidate=None):
        self.candidate = candidate
        self.calls = 0

    async def candidates_before(
        self, now: datetime, limit: int = 100
    ) -> list[PurgeCandidate]:
        return [self.candidate] if self.candidate else []

    async def get_for_purge(self, workspace_id):
        return self.candidate

    async def purge_workspace(self, workspace_id):
        self.calls += 1
        return SimpleNamespace(disposition=PurgeDisposition.PURGED)


class Memberships:
    async def remove_workspace_memberships(self, workspace_id):
        return None


class _Task:
    def __init__(self) -> None:
        from uuid import UUID

        self.task_id: UUID = uuid4()
        self.input_ref: str | None = str(uuid4())


class Context(_Context):
    def __init__(self, *, cancelled=False):
        self.task = _Task()
        self.attempt_id = uuid4()
        self.execution_epoch = 3
        self.cancelled = cancelled

    async def checkpoint(self):
        if self.cancelled:
            from task_runtime.runtime import CancellationRequested

            raise CancellationRequested


@pytest.mark.asyncio
async def test_payload_identity_has_no_secret_fields():
    from app_core.workspace.application.purge import PurgePolicy

    payload = PurgePolicy.payload(PurgeCandidate(uuid4(), datetime.now(UTC))).as_dict()
    assert set(payload) == {
        "workspaceId",
        "purgeEligibleAt",
        "schemaVersion",
        "handlerVersion",
    }
    assert "secret" not in str(payload).lower()
    assert "password" not in str(payload).lower()


@pytest.mark.asyncio
async def test_cancel_checkpoint_prevents_purge_and_effect():
    purge = Purge(PurgeCandidate(uuid4(), datetime.now(UTC)))
    with pytest.raises(Exception, match=""):
        await LifecyclePurgeHandler(
            PurgeWorkspace(purge, Memberships()), Effects()
        ).execute(Context(cancelled=True))
    assert purge.calls == 0


@pytest.mark.asyncio
async def test_stale_epoch_effect_is_rejected():
    purge = Purge(PurgeCandidate(uuid4(), datetime.now(UTC)))
    with pytest.raises(StaleAttemptError):
        await LifecyclePurgeHandler(
            PurgeWorkspace(purge, Memberships()), Effects()
        ).execute(Context())
    assert purge.calls == 1


@pytest.mark.asyncio
async def test_noneligible_workspace_is_safe_noop():
    purge = Purge()
    workspace_id = uuid4()
    result = await PurgeWorkspace(purge, Memberships()).execute(workspace_id)
    assert result.disposition == PurgeDisposition.MISSING
    assert purge.calls == 0
