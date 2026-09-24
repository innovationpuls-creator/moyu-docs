from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


@dataclass(frozen=True)
class FailedTaskDiagnostic:
    task_id: UUID
    task_type: str
    failure_code: str | None
    attempt_id: UUID | None
    execution_epoch: int | None
    finished_at: datetime | None
    next_attempt_at: datetime | None
    outbox_event_id: UUID | None


class PostgresTaskDiagnostics:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def failed_at_maturity(self) -> list[FailedTaskDiagnostic]:
        result = await self._session.execute(
            text(
                "SELECT t.task_id,t.task_type,t.failure_code,t.finished_at,"
                "t.next_attempt_at,a.attempt_id,a.execution_epoch,oe.event_id "
                "FROM work.tasks t "
                "LEFT JOIN work.task_attempts a ON a.attempt_id=t.current_attempt_id "
                "LEFT JOIN LATERAL (SELECT event_id FROM integration.outbox_events "
                "WHERE aggregate_id=t.task_id AND event_type='event.task.failed.v1' "
                "ORDER BY created_at DESC LIMIT 1) oe ON true "
                "WHERE t.state='Failed' OR (t.state='Retrying' AND t.retry_count >= 1)"
            )
        )
        return [
            FailedTaskDiagnostic(
                task_id=row["task_id"],
                task_type=row["task_type"],
                failure_code=row["failure_code"],
                attempt_id=row["attempt_id"],
                execution_epoch=row["execution_epoch"],
                finished_at=row["finished_at"],
                next_attempt_at=row["next_attempt_at"],
                outbox_event_id=row["event_id"],
            )
            for row in result.mappings().all()
        ]
