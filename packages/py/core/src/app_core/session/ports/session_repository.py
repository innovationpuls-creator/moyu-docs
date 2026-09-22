from __future__ import annotations

from abc import ABC, abstractmethod
from uuid import UUID

from app_core.session.domain.session import Session


class SessionRepositoryPort(ABC):
    @abstractmethod
    async def create_device_session_atomically(
        self, account_id: UUID, device_id: str, new_session: Session
    ) -> tuple[Session, list[Session]]:
        """Create a session and replace excess active sessions atomically."""

    @abstractmethod
    async def find_by_id(self, session_id: UUID) -> Session | None:
        """Return a session by its stable identity."""

    @abstractmethod
    async def revoke_all_sessions(self, account_id: UUID, reason: str) -> list[UUID]:
        """Revoke all active sessions for an account."""

    @abstractmethod
    async def mark_logged_out(self, session_id: UUID) -> None:
        """Log out one active session; repeated calls are no-ops."""

    @abstractmethod
    async def update_last_strong_auth(self, session: Session) -> None:
        """Persist successful recent authentication for one active session."""
