"""Global exception handlers -> canonical ErrorEnvelope (doc 28 §28-§31, §55).

Every external error response is the generated ``ErrorEnvelope`` projection
(category / errorCode / messageKey / message / requestId / retryable +
optional fieldErrors / details). messageKey, category and retryable are taken
from the canonical ``contracts/errors/error-codes.yaml`` registry wherever the
errorCode is registered (the catalog is authoritative, doc 28 §28); the
remaining envelope-level codes emitted here — request-validation 422, HTTP
status mappings and the generic 500 — are documented API-layer codes
(REQUEST_VALIDATION_ERROR / NOT_FOUND / METHOD_NOT_ALLOWED / BAD_REQUEST /
UNAUTHENTICATED / FORBIDDEN / CONFLICT / INTERNAL_ERROR) that fall back to
``messageKey == errorCode`` and ``retryable = False`` and are tracked by
tests/contract/test_contract_schemas.py as documented envelope codes.

HTTP status mapping (Constitution §3.19 categories):
  Validation -> 422, Authentication -> 401, Permission -> 403,
  NotFound -> 404, Conflict -> 409, RateLimit -> 429, others -> 500.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Mapping
from functools import lru_cache
from typing import Any

import yaml
from app_contracts.errors.error_envelope import (
    AuthErrorCategory,
    ErrorEnvelope,
    FieldError,
)
from app_core.common.exceptions import DomainError
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from api.config import settings
from api.middleware.request_context import redact_sensitive_path

logger = logging.getLogger("dom.api.error")

_CATEGORY_STATUS: dict[str, int] = {
    "Validation": 422,
    "Authentication": 401,
    "Permission": 403,
    "NotFound": 404,
    "Conflict": 409,
    "RateLimit": 429,
    "Timeout": 504,
    "DependencyFailure": 502,
    "Unavailable": 503,
    "Internal": 500,
}

# StarletteHTTPException (undefined route 404, method 405, ...) -> envelope.
_HTTP_STATUS_TO_ERROR: dict[int, tuple[str, str]] = {
    400: ("Validation", "BAD_REQUEST"),
    401: ("Authentication", "UNAUTHENTICATED"),
    403: ("Permission", "FORBIDDEN"),
    404: ("NotFound", "NOT_FOUND"),
    405: ("NotFound", "METHOD_NOT_ALLOWED"),
    409: ("Conflict", "CONFLICT"),
    429: ("RateLimit", "RATE_LIMITED"),
}

# Pydantic RequestValidationError per-field stable codes (registry-aligned
# where possible; EMAIL_INVALID / PASSWORD_TOO_WEAK are registered).
_FIELD_ERROR_CODES: dict[str, str] = {
    "email": "EMAIL_INVALID",
    "password": "PASSWORD_TOO_WEAK",
}


@lru_cache(maxsize=1)
def _error_code_catalog() -> dict[str, dict[str, Any]]:
    """Canonical error-code registry (contracts/errors/error-codes.yaml,
    doc 28 §28). Loaded once; a missing file fails loudly (no fallback).
    The contracts directory comes from configured ``CONTRACTS_DIR`` (api
    settings), so the registry resolves identically in source checkout and
    wheel-installed deployment images — never from ``__file__`` path math."""
    path = settings.contracts_dir / "errors" / "error-codes.yaml"
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    return {code: meta for code, meta in raw["codes"].items()}


def _build_envelope(
    *,
    category: str,
    error_code: str,
    message: str | None = None,
    retryable: bool | None = None,
    field_errors: list[FieldError] | None = None,
    details: dict[str, Any] | None = None,
    request_id: uuid.UUID | None = None,
) -> ErrorEnvelope:
    if request_id is None:
        from api.middleware.request_context import request_id_ctx

        stamped = request_id_ctx.get()
        if stamped:
            request_id = uuid.UUID(stamped)
    meta = _error_code_catalog().get(error_code)
    if meta is not None:
        # Registered errorCodes are canonical (doc 28 §28): the catalog's
        # category is authoritative even if the raising code path used a
        # broader exception class (e.g. a defensive ConflictError that means
        # NotFound); unregistered codes keep the exception's own category.
        category = str(meta["category"])
        retryable = bool(meta["retryable"])
    message_key = str(meta["messageKey"]) if meta else error_code
    return ErrorEnvelope(
        category=AuthErrorCategory(category),
        errorCode=error_code,
        messageKey=message_key,
        message=message,
        requestId=request_id or uuid.uuid4(),
        retryable=bool(retryable),
        fieldErrors=field_errors,
        details=details,
    )


def _json_response(
    status_code: int,
    envelope: ErrorEnvelope,
    headers: Mapping[str, str] | None = None,
) -> JSONResponse:
    # mode="json" renders enums (category) and UUIDs as JSON-native scalars.
    return JSONResponse(
        status_code=status_code,
        content=envelope.model_dump(mode="json"),
        headers=headers,
    )


async def _domain_error_handler(request: Request, exc: DomainError) -> JSONResponse:
    status = _CATEGORY_STATUS.get(exc.category, 500)
    envelope = _build_envelope(
        category=exc.category, error_code=exc.error_code, message=exc.message
    )
    return _json_response(status, envelope)


async def _request_validation_handler(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    field_errors: list[FieldError] = []
    for error in exc.errors():
        loc = error.get("loc") or ()
        field = ".".join(str(part) for part in loc if part != "body")
        code = _FIELD_ERROR_CODES.get(field, "REQUEST_VALIDATION_ERROR")
        field_errors.append(
            FieldError(
                field=field,
                code=code,
                message=str(error.get("msg", "")),
            )
        )
    envelope = _build_envelope(
        category="Validation",
        error_code="REQUEST_VALIDATION_ERROR",
        message="请求参数校验失败",
        field_errors=field_errors,
    )
    return _json_response(422, envelope)


async def _http_exception_handler(
    request: Request, exc: StarletteHTTPException
) -> JSONResponse:
    category, error_code = _HTTP_STATUS_TO_ERROR.get(
        exc.status_code, ("Internal", "INTERNAL_ERROR")
    )
    # Routes may pass a catalog errorCode as ``detail`` (e.g.
    # RESOURCE_NOT_FOUND); honor it when it is a registered code so clients
    # get the canonical code, not a generic status mapping.
    detail_code = str(exc.detail) if isinstance(exc.detail, str) else ""
    catalog = _error_code_catalog()
    if detail_code in catalog:
        error_code = detail_code
        category = str(catalog[detail_code]["category"])
    envelope = _build_envelope(
        category=category, error_code=error_code, message=exc.detail
    )
    return _json_response(exc.status_code, envelope, headers=exc.headers)


async def _unhandled_exception_handler(
    request: Request, exc: Exception
) -> JSONResponse:
    # Never leak stack traces / internals (doc 28 §31): log server-side, send a
    # generic Internal envelope to the client.
    logger.exception(
        "unhandled exception on %s %s",
        request.method,
        redact_sensitive_path(request.url.path),
    )
    envelope = _build_envelope(
        category="Internal",
        error_code="INTERNAL_ERROR",
        message="Internal server error",
    )
    return _json_response(500, envelope)


def register_error_handlers(app: FastAPI) -> None:
    # Starlette types handlers as (Request, Exception); FastAPI invokes them
    # with the registered exception type, so the narrower parameter is correct
    # (mypy arg-type is a known variance limitation).
    app.add_exception_handler(DomainError, _domain_error_handler)  # type: ignore[arg-type]
    app.add_exception_handler(
        RequestValidationError,
        _request_validation_handler,  # type: ignore[arg-type]
    )
    app.add_exception_handler(
        StarletteHTTPException,
        _http_exception_handler,  # type: ignore[arg-type]
    )
    app.add_exception_handler(Exception, _unhandled_exception_handler)
