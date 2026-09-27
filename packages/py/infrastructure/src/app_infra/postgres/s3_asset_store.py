"""S3-compatible object store for Resource Assets (arch 12).

Implements the AssetStore protocol (put/get/delete) with SigV4-signed
requests over httpx (no boto dependency; S3-compatible endpoints OK).
Missing credentials must raise, never silently fall back to the disk store.
"""

from __future__ import annotations

import hashlib
import hmac
from datetime import UTC, datetime
from typing import Any
from urllib.parse import quote, urlsplit, urlunsplit

import httpx

SERVICE = "s3"


class S3StoreError(Exception):
    pass


def _hmac(key: bytes, msg: bytes) -> bytes:
    return hmac.new(key, msg, hashlib.sha256).digest()


def _sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _canonical_request(
    method: str, path: str, headers: dict[str, str], payload_hash: str
) -> str:
    canonical_headers = "".join(
        f"{name}:{value.strip()}\n" for name, value in sorted(headers.items())
    )
    signed_headers = ";".join(sorted(headers))
    return "\n".join(
        (
            method,
            path or "/",
            "",
            canonical_headers,
            signed_headers,
            payload_hash,
        )
    )


class S3AssetStore:
    """SigV4-signed S3 API client; matches the core AssetStore protocol."""

    def __init__(
        self,
        endpoint_url: str,
        region: str,
        access_key: str,
        secret_key: str,
        bucket: str,
        addressing_style: str = "path",
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        if not all((endpoint_url, region, access_key, secret_key, bucket)):
            raise S3StoreError("S3 asset store requires endpoint/credentials/bucket")
        if addressing_style not in {"path", "virtual"}:
            raise S3StoreError("S3 addressing style must be 'path' or 'virtual'")
        self._endpoint = endpoint_url.rstrip("/")
        self._region = region
        self._access = access_key
        self._secret = secret_key
        self._bucket = bucket
        self._addressing_style = addressing_style
        self._transport = transport

    def _target(self, storage_key: str) -> tuple[str, str, str]:
        endpoint = urlsplit(self._endpoint)
        encoded_key = quote(storage_key, safe="/")
        if self._addressing_style == "virtual":
            host = f"{self._bucket}.{endpoint.netloc}"
            path = f"{endpoint.path.rstrip('/')}/{encoded_key}"
        else:
            host = endpoint.netloc
            path = f"{endpoint.path.rstrip('/')}/{self._bucket}/{encoded_key}"
        return urlunsplit((endpoint.scheme, host, path, "", "")), path, host

    def _auth_headers(
        self, method: str, path: str, body: bytes, host: str
    ) -> dict[str, str]:
        payload_hash = _sha256_hex(body)
        now = datetime.now(UTC)
        amz_date = now.strftime("%Y%m%dT%H%M%SZ")
        date_stamp = now.strftime("%Y%m%d")
        headers = {
            "host": host,
            "x-amz-content-sha256": payload_hash,
            "x-amz-date": amz_date,
        }
        canonical = _canonical_request(method, path, headers, payload_hash)
        scope = f"{date_stamp}/{self._region}/{SERVICE}/aws4_request"
        string_to_sign = "\n".join(
            (
                "AWS4-HMAC-SHA256",
                amz_date,
                scope,
                _sha256_hex(canonical.encode()),
            )
        )
        date_key = _hmac(("AWS4" + self._secret).encode(), date_stamp.encode())
        region_key = _hmac(date_key, self._region.encode())
        service_key = _hmac(region_key, SERVICE.encode())
        signing_key = _hmac(service_key, b"aws4_request")
        signature = hmac.new(
            signing_key, string_to_sign.encode(), hashlib.sha256
        ).hexdigest()
        headers["authorization"] = (
            f"AWS4-HMAC-SHA256 Credential={self._access}/{scope}, "
            f"SignedHeaders={';'.join(sorted(headers))}, Signature={signature}"
        )
        return headers

    async def put(self, storage_key: str, data: bytes) -> None:
        await self._request("PUT", storage_key, data)

    async def get(self, storage_key: str) -> bytes:
        response = await self._request("GET", storage_key, None)
        return response.content

    async def delete(self, storage_key: str) -> None:
        await self._request("DELETE", storage_key, None)

    async def _request(
        self, method: str, storage_key: str, body: bytes | None
    ) -> httpx.Response:
        url, path, host = self._target(storage_key)
        payload = body if body is not None else b""
        headers = self._auth_headers(method, path, payload, host)
        client_options: dict[str, Any] = {"timeout": 30.0}
        if self._transport is not None:
            client_options["transport"] = self._transport
        async with httpx.AsyncClient(**client_options) as client:
            try:
                response = await client.request(
                    method, url, content=payload, headers=headers
                )
            except httpx.HTTPError as exc:
                raise S3StoreError(f"s3 request failed: {exc}") from exc
        if response.status_code >= 400:
            raise S3StoreError(
                f"s3 {method} {storage_key}: status {response.status_code}"
            )
        return response
