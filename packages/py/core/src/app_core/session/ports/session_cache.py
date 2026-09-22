from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from app_core.session.domain.session import Session, SessionStatus

# Default cache TTL bounding multi-instance staleness: a revoked session must
# stop being accepted across instances within 5s (FR-AUTH-015).
SESSION_CACHE_DEFAULT_TTL_SECONDS = 5


@dataclass(frozen=True)
class SessionCachedData:
    """Disposable snapshot of a session for fast validation paths.

    Cached values are never authority: PostgreSQL is the source of truth and a
    cache hit must still be re-validated against authoritative state for
    high-risk operations (docs/architecture/16 §80, §125-126).
    """

    session_id: UUID
    account_id: UUID
    device_id: str
    status: SessionStatus
    expires_at: datetime
    last_strong_auth_at: datetime


class SessionCachePort(ABC):
    @abstractmethod
    async def get_session(self, session_id: UUID) -> SessionCachedData | None:
        """Return the cached session snapshot, or None on a miss/expiry."""

    @abstractmethod
    async def set_session(
        self, session: Session, ttl_seconds: int = SESSION_CACHE_DEFAULT_TTL_SECONDS
    ) -> None:
        """Cache a session snapshot under key ``session:{session_id}``.

        The short default TTL (5s) bounds multi-instance staleness so a
        revoked session cannot remain accepted across instances for long
        (FR-AUTH-015: cross-instance convergence <= 5s).
        """

    @abstractmethod
    async def invalidate_session(self, session_id: UUID) -> None:
        """Delete the cached entry and broadcast an invalidation event."""

    @abstractmethod
    async def publish_invalidation(self, session_id: UUID, reason: str) -> None:
        """Broadcast an invalidation event carrying a revocation reason."""
