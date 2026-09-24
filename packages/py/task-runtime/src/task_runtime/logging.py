"""Generic structured JSON logging for Task Runtime consumers (arch 23 §10).

The canonical field set is shared across services (api copies the same shape);
this module is the task-runtime side so worker processes get JSON records
without importing application code.
"""

from __future__ import annotations

import json
import logging
import os
from datetime import UTC, datetime


class JsonFormatter(logging.Formatter):
    def __init__(self, *, service: str) -> None:
        super().__init__()
        self._service = service

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, object] = {
            "timestamp": datetime.now(UTC).isoformat(),
            "level": record.levelname,
            "service": self._service,
            "logger": record.name,
            "message": record.getMessage(),
        }
        for key in (
            "requestId",
            "traceId",
            "operation",
            "result",
            "status",
            "duration_ms",
            "errorCode",
            "taskId",
            "taskType",
            "attemptNumber",
            "workerId",
        ):
            value = getattr(record, key, None)
            if value is not None:
                payload[key] = value
        return json.dumps(payload, ensure_ascii=False, default=str)


def configure_logging(*, service: str = "worker") -> None:
    level = os.environ.get("LOG_LEVEL", "INFO").upper()
    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter(service=service))
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(level)
