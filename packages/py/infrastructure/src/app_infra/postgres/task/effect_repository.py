from __future__ import annotations

from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from task_runtime.domain import StaleAttemptError


class PostgresTaskEffectRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def record_effect(
        self,
        task_id: UUID,
        effect_key: str,
        effect_type: str,
        target_ref: dict[str, Any],
        *,
        attempt_id: UUID,
        execution_epoch: int,
    ) -> UUID:
        effect_id = uuid4()
        result = await self._session.execute(
            text(
                "INSERT INTO work.task_effects "
                "(effect_id,task_id,effect_key,effect_type,target_ref,status) "
                "SELECT :effect_id,t.task_id,:effect_key,:effect_type,"
                "CAST(:target_ref AS jsonb),'Pending' FROM work.tasks t "
                "WHERE t.task_id=:task_id AND t.current_attempt_id=:attempt_id "
                "AND t.execution_epoch=:execution_epoch RETURNING effect_id"
            ),
            {
                "effect_id": effect_id,
                "task_id": task_id,
                "attempt_id": attempt_id,
                "execution_epoch": execution_epoch,
                "effect_key": effect_key,
                "effect_type": effect_type,
                "target_ref": __import__("json").dumps(target_ref),
            },
        )
        if result.rowcount == 0:  # type: ignore[attr-defined]
            raise StaleAttemptError("attempt is no longer authoritative")
        return effect_id
