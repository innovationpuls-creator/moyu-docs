from __future__ import annotations

import json
from datetime import datetime
from uuid import UUID

from app_core.session.domain.session import Session, SessionStatus
from app_core.session.ports.session_cache import (
    SESSION_CACHE_DEFAULT_TTL_SECONDS,
    SessionCachedData,
    SessionCachePort,
)
from redis.asyncio import Redis

SESSION_INVALIDATION_CHANNEL = "events:session_invalidated"


def session_cache_key(session_id: UUID) -> str:
    return f"session:{session_id}"


class ValkeySessionCache(SessionCachePort):
    """Session cache adapter backed by Valkey.

    Key pattern ``session:{session_id}`` with a short default TTL (5s). The
    shared Valkey makes a delete instantly visible to every instance; the TTL
    bounds staleness even if an invalidation event is delayed, and the
    ``events:session_invalidated`` pubsub channel notifies any instance with a
    local mirror to evict immediately (FR-AUTH-015, docs/architecture/16
    §80, §125-126).
    """

    def __init__(self, client: Redis) -> None:
        self._client = client

    async def get_session(self, session_id: UUID) -> SessionCachedData | None:
        raw = await self._client.get(session_cache_key(session_id))
        if raw is None:
            return None
        try:
            payload = json.loads(raw)
            return SessionCachedData(
                session_id=UUID(payload["session_id"]),
                account_id=UUID(payload["account_id"]),
                device_id=payload["device_id"],
                status=SessionStatus(payload["status"]),
                expires_at=datetime.fromisoformat(payload["expires_at"]),
                last_strong_auth_at=datetime.fromisoformat(
                    payload["last_strong_auth_at"]
                ),
            )
        except (KeyError, TypeError, ValueError):
            # Cache is disposable; a corrupt entry is a miss and the caller
            # falls back to authoritative PostgreSQL state.
            return None

    async def set_session(
        self, session: Session, ttl_seconds: int = SESSION_CACHE_DEFAULT_TTL_SECONDS
    ) -> None:
        payload = {
            "session_id": str(session.session_id),
            "account_id": str(session.account_id),
            "device_id": session.device_id,
            "status": session.status.value,
            "expires_at": session.expires_at.isoformat(),
            "last_strong_auth_at": session.last_strong_auth_at.isoformat(),
        }
        await self._client.set(
            session_cache_key(session.session_id),
            json.dumps(payload),
            ex=ttl_seconds,
        )

    async def invalidate_session(self, session_id: UUID) -> None:
        await self._client.delete(session_cache_key(session_id))
        # The reason is unknown at this layer; callers that know *why* the
        # session was revoked use publish_invalidation with an explicit reason.
        await self._client.publish(
            SESSION_INVALIDATION_CHANNEL,
            json.dumps({"session_id": str(session_id), "reason": None}),
        )

    async def publish_invalidation(self, session_id: UUID, reason: str) -> None:
        """Broadcast an invalidation event on ``events:session_invalidated``.

        The payload carries ``session_id`` and the ``reason`` so subscribers
        can evict their local copy and log why (e.g. ``NewDeviceLogin``,
        ``UserLogout``).
        """
        await self._client.publish(
            SESSION_INVALIDATION_CHANNEL,
            json.dumps({"session_id": str(session_id), "reason": reason}),
        )
