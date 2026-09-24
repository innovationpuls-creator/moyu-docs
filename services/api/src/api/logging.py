"""Structured JSON logging for the API service (arch 23 §10)."""

from __future__ import annotations

import json
import logging
import os
from datetime import UTC, datetime

from api.middleware.request_context import request_id_ctx, trace_id_ctx


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, object] = {
            "timestamp": datetime.now(UTC).isoformat(),
            "level": record.levelname,
            "service": "api",
            "logger": record.name,
            "message": record.getMessage(),
        }
        for key in (
            "requestId",
            "traceId",
            "operation",
            "result",
            "status",
            "method",
            "path",
            "duration_ms",
            "errorCode",
            "userId",
            "workspaceId",
            "taskId",
        ):
            value = getattr(record, key, None)
            if value is not None:
                payload[key] = value
        request_id = request_id_ctx.get()
        if request_id and "requestId" not in payload:
            payload["requestId"] = request_id
        trace_id = trace_id_ctx.get()
        if trace_id and "traceId" not in payload:
            payload["traceId"] = trace_id
        return json.dumps(payload, ensure_ascii=False, default=str)


def configure_logging() -> None:
    level = os.environ.get("LOG_LEVEL", "INFO").upper()
    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(level)
    # FastAPI/uvicorn access logs stay as-is (their own format); our own
    # structured records go through the JSON handler.
