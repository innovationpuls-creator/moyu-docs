"""Fixed-window rate limiter for Public API routes (arch 22 hardening):
per key-owner counter in Valkey; non-blocking, defaults to a generous
per-minute budget so the dev harness stays ergonomic."""

from __future__ import annotations

from typing import Any

PUBLIC_DEFAULT_LIMIT = 120
PUBLIC_WINDOW_SECONDS = 60


class PublicRateLimitExceeded(Exception):
    pass


class PublicApiRateLimiter:
    def __init__(
        self,
        client: Any,
        *,
        limit: int = PUBLIC_DEFAULT_LIMIT,
        window_seconds: int = PUBLIC_WINDOW_SECONDS,
        now_provider: Any | None = None,
    ) -> None:
        self._client = client
        self._limit = limit
        self._window = window_seconds
        self._now = now_provider or _default_now

    async def check_and_record(self, owner: str, route: str) -> None:
        key = self._key_for(owner, route)
        current = await self._client.get(key)
        count = int(current) if current is not None else 0
        if count >= self._limit:
            raise PublicRateLimitExceeded("public rate limit exceeded")
        pipeline = self._client.pipeline()
        pipeline.incr(key)
        if count == 0:
            pipeline.expire(key, self._window)
        await pipeline.execute()

    def _key_for(self, owner: str, route: str) -> str:
        return f"ratelimit:public:{owner}:{route}"

    def limit(self) -> int:
        return self._limit

    def window_seconds(self) -> int:
        return self._window

    async def usage(self, owner: str, route: str) -> int:
        """Current window's request count (metering surface, arch 22)."""
        current = await self._client.get(self._key_for(owner, route))
        return int(current) if current is not None else 0


def _default_now() -> int:
    import time

    return int(time.time())
