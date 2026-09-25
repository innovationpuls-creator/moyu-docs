"""Guarded proof: provider selection is env-driven and never partial-falls back."""

from __future__ import annotations

import pytest
from api.infra.asset_storage import get_asset_store
from app_infra.postgres.local_asset_store import LocalDiskAssetStore
from app_infra.postgres.s3_asset_store import S3AssetStore, S3StoreError

_S3_KEYS = (
    "S3_ASSET_ENDPOINT",
    "S3_ASSET_REGION",
    "S3_ASSET_ACCESS_KEY",
    "S3_ASSET_SECRET_KEY",
    "S3_ASSET_BUCKET",
)


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in _S3_KEYS:
        monkeypatch.delenv(key, raising=False)


def test_no_s3_env_uses_disk_store() -> None:
    assert isinstance(get_asset_store(), LocalDiskAssetStore)


def test_partial_s3_env_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("S3_ASSET_ENDPOINT", "http://127.0.0.1:9000")
    with pytest.raises(S3StoreError):
        get_asset_store()


def test_full_s3_env_selects_s3_store(monkeypatch: pytest.MonkeyPatch) -> None:
    values = {
        "S3_ASSET_ENDPOINT": "http://127.0.0.1:9000",
        "S3_ASSET_REGION": "us-east-1",
        "S3_ASSET_ACCESS_KEY": "ak",
        "S3_ASSET_SECRET_KEY": "sk",
        "S3_ASSET_BUCKET": "dom-assets",
    }
    for key, value in values.items():
        monkeypatch.setenv(key, value)
    assert isinstance(get_asset_store(), S3AssetStore)
