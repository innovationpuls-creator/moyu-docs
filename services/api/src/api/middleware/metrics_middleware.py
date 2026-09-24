"""Request counters (arch 15 §observability): every response bumps the
process-local metrics registry; the /v1/ops/metrics endpoint exposes it."""

from __future__ import annotations

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from api.infra.metrics import get_metrics, get_shared_metrics


class MetricsMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: object) -> Response:
        metrics = get_metrics()
        metrics.inc("requests.total")
        response = await call_next(request)  # type: ignore[operator]
        status = str(response.status_code)
        metrics.inc(f"requests.status.{status}")
        shared = get_shared_metrics()
        if shared is not None:
            # mirror the top-level counter into the shared namespace so
            # multi-instance aggregates include this process
            shared.inc("requests.total")
        return response
