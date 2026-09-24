from __future__ import annotations

import json
from typing import NotRequired, TypedDict

from app_core.account.ports.idempotency_repository import (
    IdempotencyRecord,
    IdempotencyState,
)
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

_KEY_PREFIX = "workspace:create:"


class _IdempotencyEnvelope(TypedDict):
    request_fingerprint: str
    response: NotRequired[dict[str, object]]


class PostgresWorkspaceIdempotencyRepository:
    """Workspace-create idempotency in the caller-managed transaction."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(self, key: str) -> IdempotencyRecord | None:
        stored = await self._session.scalar(
            text(
                "SELECT response FROM integration.idempotency_records "
                "WHERE idempotency_key=:key"
            ),
            {"key": _storage_key(key)},
        )
        if stored is None:
            exists = await self._session.scalar(
                text(
                    "SELECT 1 FROM integration.idempotency_records "
                    "WHERE idempotency_key=:key"
                ),
                {"key": _storage_key(key)},
            )
            return (
                IdempotencyRecord(IdempotencyState.IN_PROGRESS)
                if exists is not None
                else None
            )
        envelope = _decode_envelope(stored)
        if "response" not in envelope:
            return IdempotencyRecord(IdempotencyState.IN_PROGRESS)
        return IdempotencyRecord(
            IdempotencyState.COMPLETED,
            json.dumps(envelope["response"], separators=(",", ":")).encode(),
        )

    async def get_fingerprint(self, key: str) -> str | None:
        stored = await self._session.scalar(
            text(
                "SELECT response FROM integration.idempotency_records "
                "WHERE idempotency_key=:key"
            ),
            {"key": _storage_key(key)},
        )
        if stored is None:
            return None
        return _decode_envelope(stored)["request_fingerprint"]

    async def claim(self, key: str, request_fingerprint: str) -> bool:
        result = await self._session.execute(
            text(
                "INSERT INTO integration.idempotency_records "
                "(idempotency_key, response) VALUES (:key, :response) "
                "ON CONFLICT (idempotency_key) DO NOTHING "
                "RETURNING idempotency_key"
            ),
            {
                "key": _storage_key(key),
                "response": json.dumps(
                    {"request_fingerprint": request_fingerprint},
                    separators=(",", ":"),
                ),
            },
        )
        return result.scalar_one_or_none() is not None

    async def complete(
        self, key: str, request_fingerprint: str, response: bytes
    ) -> None:
        await self._session.execute(
            text(
                "UPDATE integration.idempotency_records SET response=:response "
                "WHERE idempotency_key=:key"
            ),
            {
                "key": _storage_key(key),
                "response": json.dumps(
                    {
                        "request_fingerprint": request_fingerprint,
                        "response": json.loads(response),
                    },
                    separators=(",", ":"),
                ),
            },
        )


def _storage_key(key: str) -> str:
    return f"{_KEY_PREFIX}{key}"


def _decode_envelope(value: str | bytes) -> _IdempotencyEnvelope:
    decoded = value.decode() if isinstance(value, bytes) else value
    envelope = json.loads(decoded)
    if not isinstance(envelope, dict) or not isinstance(
        envelope.get("request_fingerprint"), str
    ):
        raise ValueError("Workspace idempotency response envelope is invalid")
    response = envelope.get("response")
    if response is not None and not isinstance(response, dict):
        raise ValueError("Workspace idempotency response envelope is invalid")
    result: _IdempotencyEnvelope = {
        "request_fingerprint": envelope["request_fingerprint"]
    }
    if response is not None:
        result["response"] = response
    return result
