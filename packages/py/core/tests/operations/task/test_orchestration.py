from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from app_core.common.exceptions import ConflictError
from app_core.operations.task import (
    ClaimTask,
    CreateTask,
    Heartbeat,
    RequestCancel,
    RetryTask,
    StaleAttemptError,
    UpdateTaskProgress,
)
from app_core.operations.task.domain import Task, TaskState


class Tasks:
    def __init__(self):
        self.task = None
        self.attempt = None
        self.progress = None
        self.tasks = {}
        self.idempotent_tasks = {}

    async def create(self, task):
        self.task = task
        self.tasks[task.task_id] = task

    async def create_idempotent(self, task):
        key = (task.actor_account_id, task.idempotency_key)
        existing = self.idempotent_tasks.get(key)
        if existing is not None:
            return existing
        await self.create(task)
        self.idempotent_tasks[key] = task
        return task

    async def get(self, task_id):
        return self.tasks.get(task_id)

    async def get_by_actor_idempotency_key(self, actor_account_id, idempotency_key):
        return self.idempotent_tasks.get((actor_account_id, idempotency_key))

    async def list_for_actor(self, actor_account_id, *, limit, offset):
        return [self.task] if self.task is not None else []

    async def save(self, task):
        self.task = task
        self.tasks[task.task_id] = task

    async def claim(self, task_id, worker_id, lease_seconds):
        self.attempt = {"task_id": task_id, "worker_id": worker_id, "epoch": 1}
        return self.attempt

    async def request_cancel(self, task_id, requested_at):
        self.task.cancel_requested_at = requested_at

    async def schedule_retry(self, task_id, next_attempt_at, failure_code):
        return None

    async def update_progress(
        self,
        task_id: UUID,
        attempt_id: UUID,
        execution_epoch: int,
        *,
        stage: str | None,
        message_code: str | None,
        current: int | None,
        total: int | None,
        percentage: Decimal | None,
    ):
        self.progress = {
            "task_id": task_id,
            "attempt_id": attempt_id,
            "execution_epoch": execution_epoch,
            "stage": stage,
            "message_code": message_code,
            "current": current,
            "total": total,
            "percentage": percentage,
        }

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
    actor_account_id = uuid4()
    repository = Tasks()
    task = await CreateTask(
        repository, task_factory=lambda task_type: Task.create(task_type)
    ).execute("maintenance.reconcile", actor_account_id=actor_account_id)

    await RequestCancel(repository).execute(task.task_id, actor_account_id)

    assert repository.task.cancel_requested_at is not None
    assert repository.task.state.value == "Queued"


@pytest.mark.asyncio
async def test_progress_percentage_requires_reported_total():
    repository = Tasks()
    task = await CreateTask(
        repository, task_factory=lambda task_type: Task.create(task_type)
    ).execute("maintenance.reconcile")

    await UpdateTaskProgress(repository).execute(
        task.task_id, uuid4(), 1, current=2, total=3
    )
    assert repository.progress["percentage"] == Decimal("66.67")
    assert repository.progress["stage"] is None
    assert repository.progress["message_code"] is None

    await UpdateTaskProgress(repository).execute(task.task_id, uuid4(), 1, current=2)
    assert repository.progress["percentage"] is None


@pytest.mark.asyncio
@pytest.mark.parametrize(("current", "total"), [(-1, None), (None, -1), (3, 2)])
async def test_invalid_internal_progress_snapshot_raises_value_error(current, total):
    repository = Tasks()
    task = await CreateTask(
        repository, task_factory=lambda task_type: Task.create(task_type)
    ).execute("maintenance.reconcile")

    with pytest.raises(ValueError, match="progress"):
        await UpdateTaskProgress(repository).execute(
            task.task_id, uuid4(), 1, current=current, total=total
        )


@pytest.mark.asyncio
async def test_retry_is_idempotent_and_preserves_source_input():
    actor_account_id = uuid4()
    idempotency_key = uuid4()
    repository = Tasks()
    source = Task.create("import.resource")
    source.actor_account_id = actor_account_id
    source.input_ref = "asset://source"
    source.state = TaskState.FAILED
    await repository.create(source)
    retry = RetryTask(
        repository,
        CreateTask(repository, task_factory=lambda task_type: Task.create(task_type)),
    )

    first = await retry.execute(source.task_id, actor_account_id, idempotency_key)
    replay = await retry.execute(source.task_id, actor_account_id, idempotency_key)

    assert replay.task_id == first.task_id
    assert first.retry_of_task_id == source.task_id
    assert first.input_ref == "asset://source"
    assert len(repository.tasks) == 2


@pytest.mark.asyncio
async def test_retry_key_reuse_for_another_source_conflicts_and_nonfailed_rejects():
    actor_account_id = uuid4()
    idempotency_key = uuid4()
    repository = Tasks()
    source = Task.create("import.resource")
    source.actor_account_id = actor_account_id
    source.state = TaskState.FAILED
    other_source = Task.create("export.resource")
    other_source.actor_account_id = actor_account_id
    other_source.state = TaskState.FAILED
    queued_source = Task.create("import.resource")
    queued_source.actor_account_id = actor_account_id
    for task in (source, other_source, queued_source):
        await repository.create(task)
    retry = RetryTask(
        repository,
        CreateTask(repository, task_factory=lambda task_type: Task.create(task_type)),
    )

    await retry.execute(source.task_id, actor_account_id, idempotency_key)
    with pytest.raises(ConflictError) as conflict:
        await retry.execute(other_source.task_id, actor_account_id, idempotency_key)
    assert conflict.value.error_code == "IDEMPOTENCY_KEY_CONFLICT"

    with pytest.raises(ConflictError) as not_retryable:
        await retry.execute(queued_source.task_id, actor_account_id, uuid4())
    assert not_retryable.value.error_code == "TASK_NOT_RETRYABLE"
    assert len(repository.idempotent_tasks) == 1
