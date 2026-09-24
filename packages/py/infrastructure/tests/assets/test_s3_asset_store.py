"""Guarded proof: S3-compatible store signs SigV4 and round-trips bytes."""

from __future__ import annotations

import asyncio
import re

import httpx
from app_infra.postgres.s3_asset_store import S3AssetStore, S3StoreError


def _echo_store() -> tuple[S3AssetStore, dict[str, object]]:
    captured: dict[str, object] = {}
    objects: dict[str, bytes] = {}

    def echo(request: httpx.Request) -> httpx.Response:
        captured["method"] = request.method
        captured["url"] = str(request.url)
        captured["auth"] = request.headers.get("Authorization")
        captured["amz"] = request.headers.get("x-amz-date")
        captured["body"] = request.content
        if request.method == "PUT":
            objects[str(request.url)] = request.content
        if request.method == "DELETE":
            objects.pop(str(request.url), None)
        return httpx.Response(
            200,
            content=objects.get(str(request.url), b""),
            headers={"ETag": '"mock"'},
        )

    store = S3AssetStore(
        endpoint_url="http://127.0.0.1:9000",
        region="us-east-1",
        access_key="ak",
        secret_key="sk",
        bucket="dom-assets",
        transport=httpx.MockTransport(echo),
    )
    return store, captured


def test_s3_put_signs_sigv4() -> None:
    store, captured = _echo_store()

    async def scenario() -> None:
        await store.put("docs/hello.txt", b"hello world")

    asyncio.run(scenario())
    assert captured["method"] == "PUT"
    assert captured["url"] == "http://127.0.0.1:9000/dom-assets/docs/hello.txt"
    auth = str(captured["auth"])
    assert auth.startswith("AWS4-HMAC-SHA256 Credential=ak/")
    assert "SignedHeaders=host;x-amz-content-sha256;x-amz-date" in auth
    assert re.search(r"Signature=[0-9a-f]{64}$", auth)
    assert captured["amz"]
    assert captured["body"] == b"hello world"


def test_s3_get_round_trips() -> None:
    store, captured = _echo_store()

    async def scenario() -> None:
        await store.put("docs/hello.txt", b"hello world")
        result = await store.get("docs/hello.txt")
        assert result == b"hello world"

    asyncio.run(scenario())
    assert captured["method"] == "GET"


def test_s3_delete_issues_delete() -> None:
    store, captured = _echo_store()

    async def scenario() -> None:
        await store.delete("docs/hello.txt")

    asyncio.run(scenario())
    assert captured["method"] == "DELETE"


def test_s3_store_requires_credentials() -> None:
    try:
        S3AssetStore(
            endpoint_url="", region="", access_key="", secret_key="", bucket=""
        )
    except S3StoreError:
        return
    raise AssertionError("expected S3StoreError for missing config")
