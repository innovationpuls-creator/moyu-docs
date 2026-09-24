from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, cast
from uuid import UUID, uuid4

from app_core.operations.task import StaleAttemptError
from app_core.operations.task.events import TaskEventPublisher, event_for_transition
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from task_runtime.domain import Task


@dataclass(frozen=True)
class ClaimResult:
    task_id: UUID
    attempt_id: UUID
    execution_epoch: int
    lease_until: datetime
    attempt_number: int


class PostgresTaskRepository:
    def __init__(
        self,
        session: AsyncSession,
        *,
        event_publisher: TaskEventPublisher | None = None,
    ) -> None:
        self._session = session
        self._event_publisher = event_publisher

    async def _emit(self, event_type: str, task: Any) -> None:
        if self._event_publisher is not None:
            await self._event_publisher.publish(event_for_transition(event_type, task))

    async def create(self, task: Any) -> bool:
        result = await self._session.execute(
            text(
                "INSERT INTO work.tasks (task_id,task_type,state,stage,priority,"
                "actor_account_id,workspace_id,resource_id,input_ref,result_ref,"
                "retry_of_task_id,retry_count,next_attempt_at,cancel_requested_at,"
                "created_at,queued_at,started_at,finished_at,failure_code,"
                "schema_version) "
                "VALUES (:task_id,:task_type,:state,:stage,:priority,:actor_account_id,"
                ":workspace_id,:resource_id,:input_ref,:result_ref,:retry_of_task_id,"
                ":retry_count,:next_attempt_at,:cancel_requested_at,:created_at,:queued_at,"
                ":started_at,:finished_at,:failure_code,:schema_version) "
                "ON CONFLICT (task_id) DO NOTHING RETURNING task_id"
            ),
            _task_params(task),
        )
        created = result.mappings().one_or_none() is not None
        if created:
            await self._emit("TaskCreated", task)
            await self._emit("TaskQueued", task)
        return created

    async def get(self, task_id: UUID) -> Any | None:
        result = await self._session.execute(
            text("SELECT * FROM work.tasks WHERE task_id=:task_id"),
            {"task_id": task_id},
        )
        row = result.mappings().one_or_none()
        if row is None:
            return None
        return Task.from_row(cast(dict[str, object], dict(row)))

    async def save(self, task: Any) -> None:
        task_id = getattr(task, "task_id")
        state = _value(getattr(task, "state", "Queued"))
        current_attempt_id = getattr(task, "current_attempt_id", None)
        execution_epoch = cast(int, getattr(task, "execution_epoch", 0))
        if state in {"Succeeded", "Failed"} and current_attempt_id is not None:
            await self.finish(
                task_id,
                current_attempt_id,
                execution_epoch,
                state == "Succeeded",
                task=task,
            )
            return
        if state == "Queued" and current_attempt_id is not None:
            await self.release_for_recovery(
                task_id, current_attempt_id, execution_epoch
            )
            return
        if state == "WaitingForUser" and current_attempt_id is not None:
            await self._session.execute(
                text(
                    "UPDATE work.task_attempts SET lease_until=now() "
                    "WHERE attempt_id=:attempt_id AND execution_epoch=:epoch"
                ),
                {"attempt_id": current_attempt_id, "epoch": execution_epoch},
            )
        await self._session.execute(
            text(
                "UPDATE work.tasks SET state=:state,stage=:stage,priority=:priority,"
                "result_ref=:result_ref,retry_count=:retry_count,next_attempt_at=:next_at,"
                "cancel_requested_at=:cancel_at,finished_at=:finished_at,"
                "failure_code=:failure_code WHERE task_id=:task_id"
            ),
            {
                "task_id": task_id,
                "state": _value(getattr(task, "state", "Queued")),
                "stage": getattr(task, "stage", None),
                "priority": _value(getattr(task, "priority", "Normal")),
                "result_ref": getattr(task, "result_ref", None),
                "retry_count": getattr(task, "retry_count", 0),
                "next_at": getattr(task, "next_attempt_at", None),
                "cancel_at": getattr(task, "cancel_requested_at", None),
                "finished_at": getattr(task, "finished_at", None),
                "failure_code": getattr(task, "failure_code", None),
            },
        )

    async def claim(
        self, task_id: UUID, worker_id: str, lease_seconds: int
    ) -> ClaimResult | None:
        attempt_id = uuid4()
        result = await self._session.execute(
            text(
                "WITH claimed AS (UPDATE work.tasks SET state='Running',"
                "current_attempt_id=:attempt_id,execution_epoch=COALESCE(execution_epoch,0)+1,"
                "started_at=COALESCE(started_at,now()),"
                "queued_at=COALESCE(queued_at,now()) "
                "WHERE task_id=:task_id AND state IN ('Queued','Retrying') "
                "AND (next_attempt_at IS NULL OR next_attempt_at<=now()) "
                "RETURNING task_id, retry_count, execution_epoch, started_at) "
                "INSERT INTO work.task_attempts "
                "(attempt_id,task_id,attempt_number,worker_id,"
                "execution_epoch,state,claimed_at,lease_until,heartbeat_at) "
                # The task-row UPDATE lock serializes claims; the unique
                # (task_id, attempt_number) constraint is the database backstop.
                "SELECT :attempt_id,task_id,(SELECT count(*) + 1 "
                "FROM work.task_attempts "
                "WHERE task_id=claimed.task_id),:worker_id,execution_epoch,'Running',"
                "now(),now()+make_interval(secs=>:lease_seconds),now() FROM claimed "
                "RETURNING task_id,attempt_id,execution_epoch,"
                "attempt_number,lease_until"
            ),
            {
                "attempt_id": attempt_id,
                "task_id": task_id,
                "worker_id": worker_id,
                "lease_seconds": lease_seconds,
            },
        )
        row = result.mappings().one_or_none()
        if row is None:
            return None
        task = await self.get(task_id)
        if task is not None:
            await self._emit("TaskStarted", task)
        return ClaimResult(
            task_id=row["task_id"],
            attempt_id=row["attempt_id"],
            execution_epoch=row["execution_epoch"],
            lease_until=row["lease_until"],
            attempt_number=row["attempt_number"],
        )

    async def claim_next(
        self, worker_id: str, lease_seconds: int
    ) -> ClaimResult | None:
        attempt_id = uuid4()
        result = await self._session.execute(
            text(
                "WITH candidate AS (SELECT task_id FROM work.tasks "
                "WHERE state IN ('Queued','Retrying') "
                "AND (next_attempt_at IS NULL OR next_attempt_at<=now()) "
                "ORDER BY CASE priority WHEN 'Interactive' THEN 0 "
                "WHEN 'Normal' THEN 1 WHEN 'Background' THEN 2 "
                "WHEN 'Maintenance' THEN 3 ELSE 4 END, created_at "
                "FOR UPDATE SKIP LOCKED LIMIT 1), claimed AS ("
                "UPDATE work.tasks SET state='Running',current_attempt_id=:attempt_id,"
                "execution_epoch=COALESCE(execution_epoch,0)+1,"
                "started_at=COALESCE(started_at,now()),"
                "queued_at=COALESCE(queued_at,now()) "
                "WHERE task_id=(SELECT task_id FROM candidate) "
                "RETURNING task_id,retry_count,execution_epoch,started_at) "
                "INSERT INTO work.task_attempts "
                "(attempt_id,task_id,attempt_number,worker_id,"
                "execution_epoch,state,claimed_at,lease_until,heartbeat_at) "
                "SELECT :attempt_id,task_id,(SELECT count(*)+1 "
                "FROM work.task_attempts "
                "WHERE task_id=claimed.task_id),:worker_id,execution_epoch,'Running',"
                "now(),"
                "now()+make_interval(secs=>:lease_seconds),now() FROM claimed "
                "RETURNING task_id,attempt_id,execution_epoch,"
                "attempt_number,lease_until"
            ),
            {
                "attempt_id": attempt_id,
                "worker_id": worker_id,
                "lease_seconds": lease_seconds,
            },
        )
        row = result.mappings().one_or_none()
        if row is None:
            return None
        task = await self.get(row["task_id"])
        if task is not None:
            await self._emit("TaskStarted", task)
        return ClaimResult(
            task_id=row["task_id"],
            attempt_id=row["attempt_id"],
            execution_epoch=row["execution_epoch"],
            lease_until=row["lease_until"],
            attempt_number=row["attempt_number"],
        )

    async def heartbeat(
        self, task_id: UUID, attempt_id: UUID, epoch: int, lease_seconds: int
    ) -> bool:
        result = await self._session.execute(
            text(
                "UPDATE work.tasks SET started_at=COALESCE(started_at,now()) "
                "WHERE task_id=:task_id AND state IN ('Running','WaitingForUser') "
                "AND current_attempt_id=:attempt_id "
                "AND execution_epoch=:epoch "
                "AND EXISTS (SELECT 1 FROM work.task_attempts a "
                "WHERE a.attempt_id=:attempt_id AND a.lease_until>now())"
            ),
            {"task_id": task_id, "attempt_id": attempt_id, "epoch": epoch},
        )
        if result.rowcount == 0:  # type: ignore[attr-defined]
            raise StaleAttemptError("attempt is no longer authoritative")
        await self._session.execute(
            text(
                "UPDATE work.task_attempts SET heartbeat_at=now(),"
                "lease_until=now()+make_interval(secs=>:lease_seconds) "
                "WHERE attempt_id=:attempt_id AND execution_epoch=:epoch"
            ),
            {"attempt_id": attempt_id, "epoch": epoch, "lease_seconds": lease_seconds},
        )
        return True

    async def finish(
        self,
        task_id: UUID,
        attempt_id: UUID,
        epoch: int,
        succeeded: bool,
        *,
        task: Any | None = None,
    ) -> None:
        target_state = "Succeeded" if succeeded else "Failed"
        result = await self._session.execute(
            text(
                "UPDATE work.tasks SET state=:state,finished_at=now(),"
                "current_attempt_id=NULL WHERE task_id=:task_id AND state='Running' "
                "AND current_attempt_id=:attempt_id AND execution_epoch=:epoch "
                "RETURNING task_id"
            ),
            {
                "task_id": task_id,
                "attempt_id": attempt_id,
                "epoch": epoch,
                "state": target_state,
            },
        )
        if result.rowcount == 0:  # type: ignore[attr-defined]
            raise StaleAttemptError("attempt is no longer authoritative")
        await self._session.execute(
            text(
                "UPDATE work.task_attempts SET state=:state,finished_at=now() "
                "WHERE attempt_id=:attempt_id AND execution_epoch=:epoch"
            ),
            {"attempt_id": attempt_id, "epoch": epoch, "state": target_state},
        )
        task = await self.get(task_id)
        if task is not None:
            await self._emit("TaskSucceeded" if succeeded else "TaskFailed", task)

    async def finish_cancelled(
        self, task_id: UUID, attempt_id: UUID, epoch: int
    ) -> None:
        result = await self._session.execute(
            text(
                "UPDATE work.tasks SET state='Cancelled',finished_at=now(),"
                "current_attempt_id=NULL WHERE task_id=:task_id AND state='Running' "
                "AND current_attempt_id=:attempt_id AND execution_epoch=:epoch "
                "RETURNING task_id"
            ),
            {"task_id": task_id, "attempt_id": attempt_id, "epoch": epoch},
        )
        if result.rowcount == 0:  # type: ignore[attr-defined]
            raise StaleAttemptError("attempt is no longer authoritative")
        await self._session.execute(
            text(
                "UPDATE work.task_attempts SET state='Cancelled',finished_at=now() "
                "WHERE attempt_id=:attempt_id AND execution_epoch=:epoch"
            ),
            {"attempt_id": attempt_id, "epoch": epoch},
        )
        task = await self.get(task_id)
        if task is not None:
            await self._emit("TaskCancelled", task)

    async def find_expired_leases(self, now: datetime) -> list[UUID]:
        rows = await self._session.execute(
            text(
                "SELECT t.task_id FROM work.tasks t "
                "JOIN work.task_attempts a ON a.attempt_id=t.current_attempt_id "
                "WHERE t.state='Running' AND a.lease_until<:now "
                "AND a.execution_epoch=t.execution_epoch"
            ),
            {"now": now},
        )
        return [row[0] for row in rows.all()]

    async def release_for_recovery(
        self, task_id: UUID, attempt_id: UUID, epoch: int
    ) -> None:
        result = await self._session.execute(
            text(
                "UPDATE work.tasks SET state='Queued',current_attempt_id=NULL "
                "WHERE task_id=:task_id AND state IN ('Running','WaitingForUser') "
                "AND current_attempt_id=:attempt_id AND execution_epoch=:epoch"
            ),
            {"task_id": task_id, "attempt_id": attempt_id, "epoch": epoch},
        )
        if result.rowcount == 0:  # type: ignore[attr-defined]
            raise StaleAttemptError("attempt is no longer authoritative")

    async def schedule_retry(
        self, task_id: UUID, next_attempt_at: datetime, failure_code: str
    ) -> None:
        await self._session.execute(
            text(
                "UPDATE work.tasks SET state='Retrying',next_attempt_at=:next_at,"
                "failure_code=:failure_code,retry_count=retry_count+1 "
                "WHERE task_id=:task_id "
                "AND state NOT IN ('Succeeded','Failed','Cancelled')"
            ),
            {
                "task_id": task_id,
                "next_at": next_attempt_at,
                "failure_code": failure_code,
            },
        )
        task = await self.get(task_id)
        if task is not None:
            await self._emit("TaskRetryScheduled", task)

    async def request_cancel(self, task_id: UUID, requested_at: datetime) -> None:
        await self._session.execute(
            text(
                "UPDATE work.tasks SET cancel_requested_at=:requested_at "
                "WHERE task_id=:task_id "
                "AND state NOT IN ('Succeeded','Failed','Cancelled')"
            ),
            {"task_id": task_id, "requested_at": requested_at},
        )

    async def _finish_for_save(self, task: Any) -> None:
        await self.finish(
            task.task_id,
            task.current_attempt_id,
            task.execution_epoch,
            _value(task.state) == "Succeeded",
            task=task,
        )


def _value(value: Any) -> str | None:
    return getattr(value, "value", value)


def _task_params(task: Any) -> dict[str, Any]:
    now = datetime.now(UTC)
    return {
        "task_id": task.task_id,
        "task_type": task.task_type,
        "state": _value(getattr(task, "state", "Created")),
        "stage": getattr(task, "stage", None),
        "priority": _value(getattr(task, "priority", "Normal")),
        "actor_account_id": getattr(task, "actor_account_id", None),
        "workspace_id": getattr(task, "workspace_id", None),
        "resource_id": getattr(task, "resource_id", None),
        "input_ref": getattr(task, "input_ref", None),
        "result_ref": getattr(task, "result_ref", None),
        "retry_of_task_id": getattr(task, "retry_of_task_id", None),
        "retry_count": getattr(task, "retry_count", 0),
        "next_attempt_at": getattr(task, "next_attempt_at", None),
        "cancel_requested_at": getattr(task, "cancel_requested_at", None),
        "created_at": getattr(task, "created_at", now) or now,
        "queued_at": getattr(task, "queued_at", None),
        "started_at": getattr(task, "started_at", None),
        "finished_at": getattr(task, "finished_at", None),
        "failure_code": getattr(task, "failure_code", None),
        "schema_version": getattr(task, "schema_version", "1.0.0"),
    }
