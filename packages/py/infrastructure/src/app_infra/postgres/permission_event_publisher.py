from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID, uuid4

from app_contracts.events.permission.permission_changed import (
    PermissionChanged,
    Role,
    ScopeType,
)
from sqlalchemy import JSON, bindparam, text
from sqlalchemy.ext.asyncio import AsyncSession

PERMISSION_CHANGED_SUBJECT = "event.permission.changed.v1"
PERMISSION_CHANGED_SCHEMA_VERSION = "1.0.0"


async def publish_permission_changed(
    session: AsyncSession,
    *,
    scope_type: str,
    scope_id: UUID,
    workspace_id: UUID,
    account_id: UUID | None,
    action: str,
    role: str | None,
    occurred_at: datetime | None = None,
) -> None:
    happened_at = occurred_at or datetime.now(UTC)
    event_id = uuid4()
    event = PermissionChanged(
        scopeType=ScopeType(scope_type),
        scopeId=scope_id,
        workspaceId=workspace_id,
        accountId=account_id,
        action=action,
        role=Role(role) if role is not None else None,
        occurredAt=happened_at,
    )
    payload = {
        "eventId": str(event_id),
        "eventType": "PermissionChanged",
        "schemaVersion": PERMISSION_CHANGED_SCHEMA_VERSION,
        "occurredAt": happened_at.isoformat(),
        "producer": "core.permission",
        "workspaceId": str(workspace_id),
        "payload": event.model_dump(mode="json", by_alias=True, exclude_none=True),
    }
    await session.execute(
        text(
            "INSERT INTO integration.outbox_events "
            "(outbox_id, event_id, event_type, schema_version, aggregate_type, "
            "aggregate_id, payload, created_at) VALUES "
            "(:outbox_id, :event_id, :event_type, :schema_version, "
            ":aggregate_type, :aggregate_id, :payload, :created_at) "
            "ON CONFLICT (event_id) DO NOTHING"
        ).bindparams(bindparam("payload", type_=JSON)),
        {
            "outbox_id": uuid4(),
            "event_id": event_id,
            "event_type": PERMISSION_CHANGED_SUBJECT,
            "schema_version": PERMISSION_CHANGED_SCHEMA_VERSION,
            "aggregate_type": scope_type.title(),
            "aggregate_id": scope_id,
            "payload": payload,
            "created_at": happened_at,
        },
    )
