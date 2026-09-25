from __future__ import annotations

import logging

import pytest
from api.middleware.error_handler import register_error_handlers
from api.middleware.request_context import (
    PublicShareAccessLogFilter,
    RequestContextMiddleware,
)
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient


class _RecordCapture(logging.Handler):
    def __init__(self) -> None:
        super().__init__()
        self.records: list[logging.LogRecord] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.records.append(record)


@pytest.mark.asyncio
async def test_share_token_path_is_redacted_without_changing_routing() -> None:
    token = "opaque-share-token"
    app = FastAPI()
    app.add_middleware(RequestContextMiddleware)

    @app.get("/v1/public/shares/{share_token}")
    async def open_share(share_token: str) -> dict[str, str]:
        return {"path": f"/v1/public/shares/{share_token}", "token": share_token}

    access_logger = logging.getLogger("dom.api.access")
    capture = _RecordCapture()
    old_level, old_disabled = access_logger.level, access_logger.disabled
    access_logger.setLevel(logging.INFO)
    access_logger.disabled = False
    access_logger.addHandler(capture)
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.get(f"/v1/public/shares/{token}")
    finally:
        access_logger.removeHandler(capture)
        access_logger.setLevel(old_level)
        access_logger.disabled = old_disabled

    assert response.status_code == 200
    assert response.json() == {
        "path": f"/v1/public/shares/{token}",
        "token": token,
    }
    assert len(capture.records) == 1
    assert capture.records[0].path == "/v1/public/shares/[REDACTED]"
    assert token not in capture.records[0].getMessage()


@pytest.mark.asyncio
async def test_exception_log_redacts_share_token_path() -> None:
    token = "opaque-exception-token"
    app = FastAPI()
    app.add_middleware(RequestContextMiddleware)
    register_error_handlers(app)

    @app.get("/v1/public/shares/{share_token}")
    async def fail_open(share_token: str) -> None:
        raise RuntimeError("share backend unavailable")

    error_logger = logging.getLogger("dom.api.error")
    capture = _RecordCapture()
    old_level, old_disabled = error_logger.level, error_logger.disabled
    error_logger.setLevel(logging.ERROR)
    error_logger.disabled = False
    error_logger.addHandler(capture)
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app, raise_app_exceptions=False),
            base_url="http://test",
        ) as client:
            response = await client.get(f"/v1/public/shares/{token}")
    finally:
        error_logger.removeHandler(capture)
        error_logger.setLevel(old_level)
        error_logger.disabled = old_disabled

    assert response.status_code == 500
    assert len(capture.records) == 1
    assert token not in capture.records[0].getMessage()
    assert "/v1/public/shares/[REDACTED]" in capture.records[0].getMessage()


def test_uvicorn_access_record_redacts_path_and_query() -> None:
    token = "opaque-uvicorn-token"
    access_logger = logging.getLogger("uvicorn.access")
    assert any(
        isinstance(log_filter, PublicShareAccessLogFilter)
        for log_filter in access_logger.filters
    )
    record = logging.LogRecord(
        name="uvicorn.access",
        level=logging.INFO,
        pathname="uvicorn/protocols/http/h11_impl.py",
        lineno=1,
        msg='%s - "%s %s HTTP/%s" %d',
        args=("127.0.0.1", "GET", f"/v1/public/shares/{token}?x={token}", "1.1", 200),
        exc_info=None,
    )

    assert all(log_filter.filter(record) for log_filter in access_logger.filters)
    assert token not in record.getMessage()
    assert "/v1/public/shares/[REDACTED]" in record.getMessage()
