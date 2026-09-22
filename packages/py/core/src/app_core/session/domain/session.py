from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum
from uuid import UUID, uuid4


class SessionStatus(StrEnum):
    ACTIVE = "Active"
    REPLACED = "Replaced"
    LOGGED_OUT = "LoggedOut"
    EXPIRED = "Expired"
    REVOKED = "Revoked"


class SessionInvalidationReason(StrEnum):
    NEW_DEVICE_LOGIN = "NewDeviceLogin"
    USER_LOGOUT = "UserLogout"
    PASSWORD_RESET = "PasswordReset"
    ACCOUNT_DISABLED = "AccountDisabled"
    ACCOUNT_DELETED = "AccountDeleted"
    EXPIRED = "Expired"
    SECURITY_REVOKE = "SecurityRevoke"


@dataclass
class Session:
    session_id: UUID
    account_id: UUID
    device_id: str
    status: SessionStatus
    created_at: datetime
    last_seen_at: datetime
    expires_at: datetime
    last_strong_auth_at: datetime
    invalidation_reason: SessionInvalidationReason | None = None
    invalidated_at: datetime | None = None
    replaced_by_session_id: UUID | None = None

    @classmethod
    def create(
        cls,
        *,
        account_id: UUID,
        device_id: str,
        at: datetime,
        last_seen_at: datetime | None = None,
    ) -> Session:
        return cls(
            session_id=uuid4(),
            account_id=account_id,
            device_id=device_id,
            status=SessionStatus.ACTIVE,
            created_at=at,
            last_seen_at=last_seen_at or at,
            expires_at=at + SessionPolicy.ABSOLUTE_EXPIRY,
            last_strong_auth_at=at,
        )

    def is_active(self, at: datetime) -> bool:
        self.expire_if_needed(at)
        return self.status is SessionStatus.ACTIVE

    def expire_if_needed(self, at: datetime) -> None:
        if self.status is not SessionStatus.ACTIVE:
            return
        if at >= self.expires_at or at >= self.last_seen_at + SessionPolicy.IDLE_EXPIRY:
            self.invalidate(
                SessionStatus.EXPIRED, SessionInvalidationReason.EXPIRED, at
            )

    def reauthenticate(self, at: datetime) -> None:
        self.last_strong_auth_at = at

    def has_recent_reauthentication(self, at: datetime) -> bool:
        return at <= self.last_strong_auth_at + SessionPolicy.REAUTHENTICATION_WINDOW

    def logout(self, at: datetime) -> None:
        if self.status is SessionStatus.ACTIVE:
            self.invalidate(
                SessionStatus.LOGGED_OUT, SessionInvalidationReason.USER_LOGOUT, at
            )

    def replace(self, by_session_id: UUID, at: datetime) -> None:
        self.invalidate(
            SessionStatus.REPLACED,
            SessionInvalidationReason.NEW_DEVICE_LOGIN,
            at,
            replaced_by_session_id=by_session_id,
        )

    def invalidate(
        self,
        status: SessionStatus,
        reason: SessionInvalidationReason,
        at: datetime,
        *,
        replaced_by_session_id: UUID | None = None,
    ) -> None:
        self.status = status
        self.invalidation_reason = reason
        self.invalidated_at = at
        self.replaced_by_session_id = replaced_by_session_id


class SessionPolicy:
    MAX_ACTIVE_DEVICE_SESSIONS = 2
    IDLE_EXPIRY = timedelta(days=30)
    ABSOLUTE_EXPIRY = timedelta(days=90)
    REAUTHENTICATION_WINDOW = timedelta(minutes=10)

    @classmethod
    def enforce_device_limit(
        cls,
        sessions: list[Session],
        incoming: Session,
        *,
        at: datetime,
    ) -> list[Session]:
        """Replace sessions that lose the device-slot race.

        A re-login on a device that already has an active session replaces the
        OLD same-device session (one device occupies exactly one quota slot),
        then the distinct-device quota caps the surviving sessions by createdAt.
        """
        active_sessions = [session for session in sessions if session.is_active(at)]
        replaced: list[Session] = []

        same_device = [
            session
            for session in active_sessions
            if session.device_id == incoming.device_id
            and session.session_id != incoming.session_id
        ]
        for session in same_device:
            session.replace(by_session_id=incoming.session_id, at=at)
            replaced.append(session)

        replaced_ids = {session.session_id for session in replaced}
        survivors = [
            session
            for session in active_sessions
            if session.session_id not in replaced_ids
        ]
        newest_per_device: dict[str, Session] = {}
        for session in survivors:
            current = newest_per_device.get(session.device_id)
            if current is None or (session.created_at, str(session.session_id)) > (
                current.created_at,
                str(current.session_id),
            ):
                newest_per_device[session.device_id] = session
        ordered = sorted(
            newest_per_device.values(),
            key=lambda session: (session.created_at, str(session.session_id)),
        )
        excess = (
            ordered[: -cls.MAX_ACTIVE_DEVICE_SESSIONS]
            if len(ordered) > cls.MAX_ACTIVE_DEVICE_SESSIONS
            else []
        )
        for session in excess:
            session.replace(by_session_id=incoming.session_id, at=at)
            replaced.append(session)
        return replaced
