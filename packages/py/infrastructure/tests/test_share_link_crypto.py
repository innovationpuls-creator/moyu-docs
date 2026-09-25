from __future__ import annotations

import base64
import os

import pytest
from app_infra.postgres.share_link_repository import (
    decode_share_link_idempotency_encryption_key,
)


def test_share_link_encryption_key_must_be_base64_encoded_32_bytes() -> None:
    key = os.urandom(32)

    assert (
        decode_share_link_idempotency_encryption_key(base64.b64encode(key).decode())
        == key
    )
    with pytest.raises(RuntimeError, match="is required"):
        decode_share_link_idempotency_encryption_key(None)
    with pytest.raises(RuntimeError, match="valid base64"):
        decode_share_link_idempotency_encryption_key("not-base64!")
    with pytest.raises(RuntimeError, match="32 bytes"):
        decode_share_link_idempotency_encryption_key(
            base64.b64encode(b"short").decode()
        )
