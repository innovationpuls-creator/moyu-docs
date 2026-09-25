import pytest
from app_core.operations.task.domain import (
    Priority,
    Task,
    TaskState,
    TaskTransitionError,
)
from task_runtime.domain import (
    AttemptState,
    CancelRequested,
    Lease,
    RetryPolicy,
)


def test_task_transitions_to_running_only_from_queued():
    task = Task.create("maintenance.reconcile", priority=Priority.NORMAL)

    task.queue()
    task.start()

    assert task.state is TaskState.RUNNING


def test_terminal_task_rejects_further_transitions():
    task = Task.create("maintenance.reconcile")
    task.queue()
    task.start()
    task.succeed()

    with pytest.raises(TaskTransitionError):
        task.queue()


def test_retry_policy_only_allows_bounded_retry():
    policy = RetryPolicy(max_attempts=2, backoff_seconds=1)

    assert policy.can_retry(1)
    assert not policy.can_retry(2)


def test_lease_rejects_stale_execution_epoch():
    lease = Lease(worker_id="w1", execution_epoch=3, lease_until=10)

    assert lease.is_valid(worker_id="w1", execution_epoch=3, now=9)
    assert not lease.is_valid(worker_id="w1", execution_epoch=2, now=9)
    assert not lease.is_valid(worker_id="w1", execution_epoch=3, now=10)


def test_cancel_request_is_not_terminal_until_checkpoint():
    request = CancelRequested()

    assert not request.completed
    request.complete()
    assert request.completed
    assert AttemptState.CANCELLED.value == "Cancelled"
