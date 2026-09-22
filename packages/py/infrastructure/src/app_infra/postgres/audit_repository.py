from __future__ import annotations

import re
from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from app_core.account.ports.audit_repository import AuditRepositoryPort
from sqlalchemy import JSON, bindparam, text
from sqlalchemy.ext.asyncio import AsyncSession


class PostgresAuditRepository(AuditRepositoryPort):
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def append(
        self,
        *,
        actor_type: str,
        action: str,
        actor_id: UUID | None = None,
        workspace_id: UUID | None = None,
        project_id: UUID | None = None,
        resource_id: UUID | None = None,
        target_ref: dict[str, Any] | None = None,
        request_id: UUID | None = None,
        trace_id: str | None = None,
        metadata: dict[str, Any] | None = None,
        occurred_at: datetime | None = None,
    ) -> UUID:
        audit_id = uuid4()
        safe_metadata = _safe_metadata(metadata)
        safe_target_ref = _safe_metadata(target_ref)
        await self._session.execute(
            text(
                """
                INSERT INTO audit.entries
                    (audit_id, occurred_at, actor_type, actor_id, action,
                     workspace_id, project_id, resource_id, target_ref,
                     request_id, trace_id, metadata)
                VALUES (:audit_id, COALESCE(:occurred_at, now()), :actor_type,
                        :actor_id, :action, :workspace_id, :project_id,
                        :resource_id, :target_ref, :request_id, :trace_id,
                        :metadata)
                """
            ).bindparams(
                bindparam("target_ref", type_=JSON),
                bindparam("metadata", type_=JSON),
            ),
            {
                "audit_id": audit_id,
                "occurred_at": occurred_at,
                "actor_type": actor_type,
                "actor_id": actor_id,
                "action": action,
                "workspace_id": workspace_id,
                "project_id": project_id,
                "resource_id": resource_id,
                "target_ref": safe_target_ref,
                "request_id": request_id,
                "trace_id": trace_id,
                "metadata": safe_metadata,
            },
        )
        return audit_id


_SENSITIVE_KEY_PARTS = frozenset({"password", "token", "secret", "credential"})
_CAMEL_CASE_BOUNDARY = re.compile(r"(?<=[a-z0-9])(?=[A-Z])")
_NON_ALPHANUMERIC = re.compile(r"[^a-z0-9]+")


def _safe_metadata(value: dict[str, Any] | None) -> dict[str, Any] | None:
    if value is None:
        return None
    return _redact_json(value)


def _redact_json(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: _redact_json(item)
            for key, item in value.items()
            if isinstance(key, str) and not _is_sensitive_key(key)
        }
    if isinstance(value, list):
        return [_redact_json(item) for item in value]
    return value


def _is_sensitive_key(key: str) -> bool:
    snake_case = _CAMEL_CASE_BOUNDARY.sub("_", key).casefold()
    key_parts = _NON_ALPHANUMERIC.split(snake_case)
    return any(part in _SENSITIVE_KEY_PARTS for part in key_parts)
