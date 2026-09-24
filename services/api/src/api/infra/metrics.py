"""Single-process metrics counters (arch 15 §observability): a tiny atomic
registry feeding GET /v1/ops/metrics. Honest boundary: this slice is
process-local; cross-instance aggregation is a deployment concern."""

from __future__ import annotations

import threading
from typing import Any


class Metrics:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._counters: dict[str, int] = {}

    def inc(self, name: str, delta: int = 1) -> None:
        with self._lock:
            self._counters[name] = self._counters.get(name, 0) + delta

    def set(self, name: str, value: int) -> None:
        with self._lock:
            self._counters[name] = value

    def snapshot(self) -> dict[str, int]:
        with self._lock:
            return dict(self._counters)

    def gauge_snapshot(self) -> dict[str, Any]:
        return {}


_metrics: Metrics | None = None


class ValkeyMetrics:
    """Shared counters via Valkey INCR (arch 14/15): multiple API instances
    aggregate into one counter namespace. Honest boundary: TTL/reset/rollup
    policies are deployment concerns beyond this slice."""

    def __init__(self, client: Any) -> None:
        self._client = client
        self._prefix = "dom:metrics:"

    def inc(self, name: str, delta: int = 1) -> None:
        import asyncio

        async def _inc() -> None:
            for _ in range(delta):
                await self._client.incr(self._prefix + name)

        loop = asyncio.get_running_loop() if _running() else None
        if loop is not None:
            loop.create_task(_inc())
        else:
            asyncio.run(_inc())

    def set(self, name: str, value: int) -> None:
        import asyncio

        async def _set() -> None:
            current = int(await self._client.get(self._prefix + name) or 0)
            await self._client.set(self._prefix + name, str(current + value))

        loop = asyncio.get_running_loop() if _running() else None
        if loop is not None:
            loop.create_task(_set())

    def snapshot(self) -> dict[str, int]:
        return {}  # live sums are read by the ops route via summarize()

    def gauge_snapshot(self) -> dict[str, Any]:
        return {}

    async def summarize(self) -> dict[str, int]:
        """Read the tracked counters from the shared namespace (aggregation
        baseline; TTL/rollup remain deployment concerns)."""
        out: dict[str, int] = {}
        for key in ("requests.total", "requests.status.200", "requests.status.401"):
            value = await self._client.get(self._prefix + key)
            if value is not None:
                out["shared." + key] = int(value)
        return out


_shared_metrics: ValkeyMetrics | None = None


def get_shared_metrics() -> ValkeyMetrics | None:
    """Lazily build the shared store when VALKEY_METRICS_URL is configured."""
    global _shared_metrics
    if _shared_metrics is None:
        import os

        url = os.environ.get("VALKEY_METRICS_URL", "")
        if not url:
            return None
        from redis import Redis

        _shared_metrics = ValkeyMetrics(Redis.from_url(url))
    return _shared_metrics


def _running() -> bool:
    import asyncio

    try:
        asyncio.get_running_loop()
        return True
    except RuntimeError:
        return False


def get_metrics() -> Metrics:
    global _metrics
    if _metrics is None:
        _metrics = Metrics()
    return _metrics
