from uuid import uuid4

import pytest
from app_core.operations.task import (
    ClaimTask,
    CreateTask,
    Heartbeat,
    RequestCancel,
    StaleAttemptError,
)
from task_runtime.domain import Task


class Tasks:
    def __init__(self):
        self.task = None
        self.attempt = None

    async def create(self, task):
        self.task = task

    async def get(self, task_id):
        return self.task

    async def save(self, task):
        self.task = task

    async def claim(self, task_id, worker_id, lease_seconds):
        self.attempt = {"task_id": task_id, "worker_id": worker_id, "epoch": 1}
        return self.attempt

    async def request_cancel(self, task_id, requested_at):
        self.task.cancel_requested_at = requested_at

    async def heartbeat(self, task_id, attempt_id, epoch, lease_seconds):
        if epoch != 1:
            raise StaleAttemptError
        return True


@pytest.mark.asyncio
async def test_create_task_persists_queued_task():
    repository = Tasks()
    task = await CreateTask(
        repository, task_factory=lambda task_type: Task.create(task_type)
    ).execute("maintenance.reconcile")

    assert repository.task is task
    assert task.state.value == "Queued"


@pytest.mark.asyncio
async def test_claim_and_heartbeat_reject_stale_epoch():
    repository = Tasks()
    task = await CreateTask(
        repository, task_factory=lambda task_type: Task.create(task_type)
    ).execute("maintenance.reconcile")
    attempt = await ClaimTask(repository).execute(task.task_id, "worker-1", 30)

    assert attempt["epoch"] == 1
    with pytest.raises(StaleAttemptError):
        await Heartbeat(repository).execute(task.task_id, uuid4(), 2, 30)


@pytest.mark.asyncio
async def test_cancel_records_request_without_faking_terminal_state():
    repository = Tasks()
    task = await CreateTask(
        repository, task_factory=lambda task_type: Task.create(task_type)
    ).execute("maintenance.reconcile")

    await RequestCancel(repository).execute(task.task_id)

    assert repository.task.cancel_requested_at is not None
    assert repository.task.state.value == "Queued"
