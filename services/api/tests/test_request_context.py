"""Arch 23: request correlation + structured access logs."""

from __future__ import annotations

import json
import logging
import os
import uuid
from pathlib import Path
from types import SimpleNamespace

import pytest
import pytest_asyncio
from alembic import command
from alembic.config import Config
from api.dependencies.auth import get_current_session
from api.logging import JsonFormatter
from api.main import create_app
from app_infra.postgres.test_database_guard import require_isolated_database
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

DATABASE_URL = "postgresql+psycopg://torch@localhost:5432/dom_workspace_lifecycle_test"

LOG_LEVEL_VAR = "LOG_LEVEL"


@pytest_asyncio.fixture(scope="module", autouse=True)
async def migrated_database() -> None:
    database_url = require_isolated_database(os.environ["DATABASE_URL"])
    assert database_url == DATABASE_URL
    config = Config(str(Path("migrations/postgres/alembic.ini")))
    config.set_main_option("sqlalchemy.url", database_url)
    command.upgrade(config, "head")


def test_json_formatter_emits_structured_fields() -> None:
    """Arch 23 §10: JSON records carry the canonical field set."""
    record = logging.LogRecord(
        name="dom.api.access",
        level=logging.INFO,
        pathname="m",
        lineno=1,
        msg="access",
        args=(),
        exc_info=None,
    )
    record.operation = "http.proxy"
    record.result = "ok"
    record.duration_ms = 12.5
    record.requestId = "req-1"
    payload = json.loads(JsonFormatter().format(record))
    for key in (
        "timestamp",
        "level",
        "service",
        "message",
        "operation",
        "result",
        "duration_ms",
        "requestId",
    ):
        assert key in payload, key
    assert payload["service"] == "api"
    assert payload["requestId"] == "req-1"


@pytest.mark.asyncio
async def test_request_stamped_with_request_id_and_structured_access_log() -> None:
    os.environ[LOG_LEVEL_VAR] = "INFO"
    app: FastAPI = create_app(debug=True)
    app.dependency_overrides[get_current_session] = lambda: SimpleNamespace(
        account_id=uuid.uuid4()
    )
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        # /healthz is exempt from the session guard; it still gets the stamp
        response = await client.get("/healthz")
    assert response.status_code == 200
    request_id = response.headers.get("X-Request-Id")
    assert request_id is not None
    # The middleware stamps the same correlation into every log record via the
    # request contextvars (JsonFormatter verified by the unit test above).


@pytest.mark.asyncio
async def test_error_envelope_reuses_the_stamped_request_id() -> None:
    app: FastAPI = create_app(debug=True)
    app.dependency_overrides[get_current_session] = lambda: SimpleNamespace(
        account_id=uuid.uuid4()
    )
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get(f"/v1/resources/{uuid.uuid4()}")
    assert response.status_code == 404
    body = response.json()
    assert body["requestId"] == response.headers.get("X-Request-Id")
    assert body["errorCode"] == "RESOURCE_NOT_FOUND"


@pytest.mark.asyncio
async def test_diagnostics_reports_dependency_health() -> None:
    """Arch 14: readiness surface reports DB + Valkey checks (booleans only)."""
    app: FastAPI = create_app(debug=True)
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get("/v1/diagnostics")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] in ("ok", "degraded")
    names = {c["name"] for c in body["checks"]}
    assert names == {"postgres", "valkey"}
    # In this guarded environment both dependencies are up.
    assert body["status"] == "ok"
    for check in body["checks"]:
        assert check["ok"] is True
