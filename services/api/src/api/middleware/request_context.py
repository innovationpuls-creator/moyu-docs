"""Request correlation context (arch 23 §4-§6): requestId + traceId stamped
on every API request; structured access records with durationMs + result."""

from __future__ import annotations

import contextvars
import logging
import time
from uuid import uuid4

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response

request_id_ctx: contextvars.ContextVar[str] = contextvars.ContextVar(
    "dom_request_id", default=""
)
trace_id_ctx: contextvars.ContextVar[str] = contextvars.ContextVar(
    "dom_trace_id", default=""
)

logger = logging.getLogger("dom.api.access")


class RequestContextMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next) -> Response:
        request_id = request.headers.get("X-Request-Id") or str(uuid4())
        trace_id = request.headers.get("X-Trace-Id") or str(uuid4())
        request_id_ctx.set(request_id)
        trace_id_ctx.set(trace_id)
        started = time.perf_counter()
        response = await call_next(request)
        duration_ms = round((time.perf_counter() - started) * 1000, 2)
        response.headers["X-Request-Id"] = request_id
        logger.info(
            "access",
            extra={
                "operation": "http.proxy",
                "result": "ok" if response.status_code < 500 else "error",
                "status": response.status_code,
                "method": request.method,
                "path": request.url.path,
                "duration_ms": duration_ms,
            },
        )
        return response
