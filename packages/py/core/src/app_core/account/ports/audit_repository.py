from __future__ import annotations

from datetime import datetime
from typing import Any, Protocol
from uuid import UUID


class AuditRepositoryPort(Protocol):
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
    ) -> UUID: ...
