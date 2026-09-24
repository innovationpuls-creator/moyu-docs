from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

import pytest
from app_core.account.ports.idempotency_repository import IdempotencyState
from app_infra.postgres.workspace_idempotency_repository import (
    PostgresWorkspaceIdempotencyRepository,
    _decode_envelope,
    _storage_key,
)


class _Result:
    def __init__(self, value: Any) -> None:
        self._value = value

    def scalar_one_or_none(self) -> Any:
        return self._value


class _Session:
    def __init__(self, *, scalar_values: list[Any], execute_values: list[Any]) -> None:
        self.scalar_values = scalar_values
        self.execute_values = execute_values
        self.calls: list[tuple[str, Mapping[str, Any]]] = []

    async def scalar(self, statement: Any, params: Mapping[str, Any]) -> Any:
        self.calls.append((str(statement), params))
        return self.scalar_values.pop(0)

    async def execute(self, statement: Any, params: Mapping[str, Any]) -> _Result:
        self.calls.append((str(statement), params))
        return _Result(self.execute_values.pop(0))


@pytest.mark.asyncio
async def test_claim_uses_namespaced_key_and_fingerprint_envelope() -> None:
    session = _Session(scalar_values=[], execute_values=["workspace:create:k1"])
    repository = PostgresWorkspaceIdempotencyRepository(session)  # type: ignore[arg-type]

    assert await repository.claim("k1", "sha256:abc") is True
    statement, params = session.calls[0]
    assert "ON CONFLICT (idempotency_key) DO NOTHING" in statement
    assert params["key"] == "workspace:create:k1"
    assert json.loads(params["response"]) == {"request_fingerprint": "sha256:abc"}


@pytest.mark.asyncio
async def test_get_returns_in_progress_when_claim_has_no_response() -> None:
    session = _Session(scalar_values=[None, 1], execute_values=[])
    repository = PostgresWorkspaceIdempotencyRepository(session)  # type: ignore[arg-type]

    record = await repository.get("k2")

    assert record is not None and record.state is IdempotencyState.IN_PROGRESS
    assert [params["key"] for _, params in session.calls] == [
        "workspace:create:k2",
        "workspace:create:k2",
    ]


@pytest.mark.asyncio
async def test_get_treats_claim_envelope_as_in_progress() -> None:
    claimed = '{"request_fingerprint":"sha256:abc"}'
    session = _Session(scalar_values=[claimed], execute_values=[])
    repository = PostgresWorkspaceIdempotencyRepository(session)  # type: ignore[arg-type]

    record = await repository.get("k-claimed")

    assert record is not None and record.state is IdempotencyState.IN_PROGRESS


@pytest.mark.asyncio
async def test_get_returns_completed_response_and_fingerprint() -> None:
    stored = json.dumps(
        {
            "request_fingerprint": "sha256:def",
            "response": {"workspaceId": "w-2", "ownerAccountId": "a-1"},
        }
    )
    session = _Session(scalar_values=[stored, stored], execute_values=[])
    repository = PostgresWorkspaceIdempotencyRepository(session)  # type: ignore[arg-type]

    record = await repository.get("k3")
    fingerprint = await repository.get_fingerprint("k3")

    assert record is not None and record.state is IdempotencyState.COMPLETED
    assert record.response == (b'{"workspaceId":"w-2","ownerAccountId":"a-1"}')
    assert fingerprint == "sha256:def"


@pytest.mark.asyncio
async def test_complete_stores_fingerprint_and_response_together() -> None:
    session = _Session(scalar_values=[], execute_values=[None])
    repository = PostgresWorkspaceIdempotencyRepository(session)  # type: ignore[arg-type]

    await repository.complete("k4", "sha256:ghi", b'{"workspaceId":"w-4"}')

    _, params = session.calls[0]
    assert params["key"] == "workspace:create:k4"
    assert json.loads(params["response"]) == {
        "request_fingerprint": "sha256:ghi",
        "response": {"workspaceId": "w-4"},
    }


def test_storage_key_uses_workspace_create_namespace() -> None:
    assert _storage_key("request-1") == "workspace:create:request-1"
    assert _storage_key("request-1") != "request-1"


def test_decode_envelope_reads_fingerprint_and_completed_response() -> None:
    envelope = _decode_envelope(
        json.dumps(
            {
                "request_fingerprint": "sha256:abc",
                "response": {"workspaceId": "workspace-1"},
            }
        )
    )

    assert envelope == {
        "request_fingerprint": "sha256:abc",
        "response": {"workspaceId": "workspace-1"},
    }


def test_decode_envelope_accepts_in_progress_claim() -> None:
    assert _decode_envelope('{"request_fingerprint":"sha256:abc"}') == {
        "request_fingerprint": "sha256:abc"
    }


@pytest.mark.parametrize(
    "payload",
    ["null", "[]", "{}", '{"request_fingerprint":1}'],
)
def test_decode_envelope_rejects_malformed_state(payload: str) -> None:
    with pytest.raises(ValueError, match="envelope is invalid"):
        _decode_envelope(payload)
