from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any, cast
from uuid import uuid4

import pytest
from app_core.assets.domain import Asset
from app_core.common.exceptions import IdempotencyConflictError
from app_infra.postgres.asset_upload_idempotency_repository import (
    PostgresAssetUploadIdempotencyRepository,
    _decode_asset,
    _encode_asset,
)
from sqlalchemy.ext.asyncio import AsyncSession

ASSET = Asset(
    asset_id=uuid4(),
    resource_id=uuid4(),
    provider="local-disk",
    storage_key="assets/test",
    size_bytes=11,
    mime="image/png",
    sha256="a" * 64,
    created_by=uuid4(),
    created_at=datetime(2026, 9, 25, tzinfo=UTC),
    original_name="diagram.png",
)


class _Session:
    def __init__(self, scalar_pops: list[Any]) -> None:
        self.scalar_pops = list(scalar_pops)
        self.calls: list[tuple[str, Mapping[str, Any]]] = []

    async def scalar(self, statement: Any, params: Mapping[str, Any]) -> Any:
        self.calls.append((str(statement), params))
        return self.scalar_pops.pop(0)

    async def execute(self, statement: Any, params: Mapping[str, Any]) -> None:
        self.calls.append((str(statement), params))


def _repository(session: _Session) -> PostgresAssetUploadIdempotencyRepository:
    return PostgresAssetUploadIdempotencyRepository(cast(AsyncSession, session))


def _completed(fingerprint: str, asset: Asset) -> str:
    return json.dumps(
        {
            "request_fingerprint": fingerprint,
            "phase": "completed",
            "asset": _encode_asset(asset),
        },
        separators=(",", ":"),
    )


async def _unexpected_operation() -> Asset:
    raise AssertionError("replay must not run upload operation")


def test_asset_serde_round_trip() -> None:
    assert _decode_asset(_encode_asset(ASSET)) == ASSET


@pytest.mark.asyncio
async def test_claim_winner_runs_and_stores_original_asset() -> None:
    session = _Session(scalar_pops=["asset:upload:actor:resource:key"])
    repository = _repository(session)
    ran: list[bool] = []

    async def operation() -> Asset:
        ran.append(True)
        return ASSET

    assert await repository.execute("actor:resource:key", "fp-1", operation) == ASSET
    assert ran == [True]
    statement, params = session.calls[-1]
    assert "UPDATE integration.idempotency_records" in statement
    envelope = json.loads(params["response"])
    assert envelope["phase"] == "completed"
    assert envelope["request_fingerprint"] == "fp-1"
    assert _decode_asset(envelope["asset"]) == ASSET


@pytest.mark.asyncio
async def test_matching_fingerprint_replays_without_running_operation() -> None:
    session = _Session(scalar_pops=[None, _completed("fp-1", ASSET)])
    repository = _repository(session)

    assert (
        await repository.execute("actor:resource:key", "fp-1", _unexpected_operation)
        == ASSET
    )


@pytest.mark.asyncio
async def test_mismatched_fingerprint_returns_stable_conflict() -> None:
    session = _Session(scalar_pops=[None, _completed("other", ASSET)])
    repository = _repository(session)

    with pytest.raises(IdempotencyConflictError) as error:
        await repository.execute("actor:resource:key", "fp-1", _unexpected_operation)

    assert error.value.error_code == "IDEMPOTENCY_KEY_CONFLICT"
