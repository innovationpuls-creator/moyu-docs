from __future__ import annotations

import json
from datetime import datetime, timezone
from uuid import UUID, uuid4

from app_core.session.domain.session import (
    Session,
    SessionInvalidationReason,
    SessionPolicy,
    SessionStatus,
)
from app_core.session.ports.session_repository import SessionRepositoryPort
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app_infra.postgres.audit_repository import PostgresAuditRepository


class PostgresSessionRepository(SessionRepositoryPort):
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create_device_session_atomically(
        self, account_id: UUID, device_id: str, new_session: Session
    ) -> tuple[Session, list[Session]]:
        await self.session.execute(
            text(
                "SELECT account_id FROM auth.accounts "
                "WHERE account_id = :account_id FOR UPDATE"
            ),
            {"account_id": account_id},
        )
        db_sessions = await self._active_sessions(account_id)
        replaced = SessionPolicy.enforce_device_limit(
            db_sessions + [new_session],
            incoming=new_session,
            at=new_session.created_at,
        )

        await self.session.execute(
            text(
                "INSERT INTO auth.sessions "
                "(session_id, account_id, device_id, status, session_version, "
                "last_strong_auth_at, created_at, last_seen_at, expires_at) "
                "VALUES (:session_id, :account_id, :device_id, :status, 1, "
                ":last_strong_auth_at, :created_at, :last_seen_at, :expires_at)"
            ),
            {
                "session_id": new_session.session_id,
                "account_id": account_id,
                "device_id": device_id,
                "status": new_session.status.value,
                "last_strong_auth_at": new_session.last_strong_auth_at,
                "created_at": new_session.created_at,
                "last_seen_at": new_session.last_seen_at,
                "expires_at": new_session.expires_at,
            },
        )

        occurred_at = datetime.now(timezone.utc)
        # Persist sessions that were logically expired at policy evaluation
        # (Session.expire_if_needed mutated them in memory) in the same
        # transaction, so the DB never retains a stale 'Active' row.
        for session in db_sessions:
            if session.status is SessionStatus.EXPIRED:
                await self.session.execute(
                    text(
                        "UPDATE auth.sessions SET status = :status, "
                        "invalidation_reason = :invalidation_reason, "
                        "replaced_at = :replaced_at "
                        "WHERE session_id = :session_id"
                    ),
                    {
                        "status": SessionStatus.EXPIRED.value,
                        "invalidation_reason": SessionInvalidationReason.EXPIRED.value,
                        "replaced_at": session.invalidated_at or occurred_at,
                        "session_id": session.session_id,
                    },
                )
        for replaced_session in replaced:
            await self.session.execute(
                text(
                    "UPDATE auth.sessions SET status = :status, "
                    "replaced_at = :replaced_at, "
                    "replaced_by_session_id = :replaced_by_session_id, "
                    "invalidation_reason = :invalidation_reason "
                    "WHERE session_id = :session_id"
                ),
                {
                    "status": SessionStatus.REPLACED.value,
                    "replaced_at": replaced_session.invalidated_at or occurred_at,
                    "replaced_by_session_id": new_session.session_id,
                    "invalidation_reason": (
                        SessionInvalidationReason.NEW_DEVICE_LOGIN.value
                    ),
                    "session_id": replaced_session.session_id,
                },
            )
            event_id = uuid4()
            replaced_at = replaced_session.invalidated_at or occurred_at
            payload = {
                "eventId": str(event_id),
                "eventType": "SessionReplaced",
                "schemaVersion": "1.0.0",
                "occurredAt": occurred_at.isoformat(),
                "producer": "services.api",
                "payload": {
                    "userId": str(account_id),
                    "replacedSessionId": str(replaced_session.session_id),
                    "replacedBySessionId": str(new_session.session_id),
                    "invalidationReason": (
                        SessionInvalidationReason.NEW_DEVICE_LOGIN.value
                    ),
                    "replacedAt": replaced_at.isoformat(),
                },
            }
            await self.session.execute(
                text(
                    "INSERT INTO integration.outbox_events "
                    "(outbox_id, event_id, event_type, schema_version, "
                    "aggregate_type, aggregate_id, payload, trace_id) "
                    "VALUES (:outbox_id, :event_id, :event_type, :schema_version, "
                    ":aggregate_type, :aggregate_id, :payload, :trace_id)"
                ),
                {
                    "outbox_id": uuid4(),
                    "event_id": event_id,
                    "event_type": "SessionReplaced",
                    "schema_version": "1.0.0",
                    "aggregate_type": "Session",
                    "aggregate_id": replaced_session.session_id,
                    "payload": json.dumps(payload),
                    "trace_id": None,
                },
            )
            await PostgresAuditRepository(self.session).append(
                actor_type="Account",
                actor_id=account_id,
                action="SessionReplaced",
                target_ref={
                    "sessionId": str(replaced_session.session_id),
                    "deviceId": replaced_session.device_id,
                },
                metadata={
                    "invalidationReason": (
                        SessionInvalidationReason.NEW_DEVICE_LOGIN.value
                    )
                },
            )

        return new_session, replaced

    async def _active_sessions(self, account_id: UUID) -> list[Session]:
        result = await self.session.execute(
            text(
                "SELECT session_id, account_id, device_id, status, created_at, "
                "last_seen_at, expires_at, last_strong_auth_at, replaced_at, "
                "replaced_by_session_id, invalidation_reason "
                "FROM auth.sessions WHERE account_id = :account_id "
                "AND status = :status ORDER BY created_at, session_id"
            ),
            {"account_id": account_id, "status": SessionStatus.ACTIVE.value},
        )
        return [self._session_from_row(row) for row in result.mappings().all()]

    async def find_by_id(self, session_id: UUID) -> Session | None:
        result = await self.session.execute(
            text(
                "SELECT session_id, account_id, device_id, status, created_at, "
                "last_seen_at, expires_at, last_strong_auth_at, replaced_at, "
                "replaced_by_session_id, invalidation_reason "
                "FROM auth.sessions WHERE session_id = :session_id"
            ),
            {"session_id": session_id},
        )
        row = result.mappings().first()
        return self._session_from_row(row) if row else None

    async def revoke_all_sessions(self, account_id: UUID, reason: str) -> list[UUID]:
        result = await self.session.execute(
            text(
                "UPDATE auth.sessions SET status = :status, replaced_at = :at, "
                "invalidation_reason = :reason "
                "WHERE account_id = :account_id AND status = :active "
                "RETURNING session_id"
            ),
            {
                "status": SessionStatus.REVOKED.value,
                "at": datetime.now(timezone.utc),
                "reason": reason,
                "account_id": account_id,
                "active": SessionStatus.ACTIVE.value,
            },
        )
        return list(result.scalars().all())

    async def mark_logged_out(self, session_id: UUID) -> None:
        await self.session.execute(
            text(
                "UPDATE auth.sessions SET status = :status, replaced_at = :at, "
                "invalidation_reason = :reason "
                "WHERE session_id = :session_id AND status = :active"
            ),
            {
                "status": SessionStatus.LOGGED_OUT.value,
                "at": datetime.now(timezone.utc),
                "reason": SessionInvalidationReason.USER_LOGOUT.value,
                "session_id": session_id,
                "active": SessionStatus.ACTIVE.value,
            },
        )

    async def update_last_strong_auth(self, session: Session) -> None:
        await self.session.execute(
            text(
                "UPDATE auth.sessions SET last_strong_auth_at = :last_strong_auth_at "
                "WHERE session_id = :session_id AND status = :active"
            ),
            {
                "last_strong_auth_at": session.last_strong_auth_at,
                "session_id": session.session_id,
                "active": SessionStatus.ACTIVE.value,
            },
        )

    @staticmethod
    def _session_from_row(row: object) -> Session:
        data = row if hasattr(row, "__getitem__") else {}
        return Session(
            session_id=data["session_id"],
            account_id=data["account_id"],
            device_id=data["device_id"],
            status=SessionStatus(data["status"]),
            created_at=data["created_at"],
            last_seen_at=data["last_seen_at"],
            expires_at=data["expires_at"],
            last_strong_auth_at=data["last_strong_auth_at"],
            invalidation_reason=(
                SessionInvalidationReason(data["invalidation_reason"])
                if data["invalidation_reason"]
                else None
            ),
            invalidated_at=data["replaced_at"],
            replaced_by_session_id=data["replaced_by_session_id"],
        )
