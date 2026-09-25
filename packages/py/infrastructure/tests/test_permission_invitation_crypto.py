from __future__ import annotations

import base64
import os

import pytest
from app_core.common.exceptions import IdempotencyConflictError
from app_infra.postgres.permission_administration_repository import (
    _decrypt_invitation_url,
    _encrypt_invitation_url,
    decode_invitation_idempotency_encryption_key,
)


@pytest.fixture
def encryption_key() -> bytes:
    return os.urandom(32)


def test_configured_key_must_be_base64_encoded_32_bytes() -> None:
    key = os.urandom(32)
    assert (
        decode_invitation_idempotency_encryption_key(base64.b64encode(key).decode())
        == key
    )
    with pytest.raises(RuntimeError, match="is required"):
        decode_invitation_idempotency_encryption_key(None)
    with pytest.raises(RuntimeError, match="32 bytes"):
        decode_invitation_idempotency_encryption_key(
            base64.b64encode(b"short").decode()
        )


def test_invitation_url_is_authenticated_encrypted_and_bound_to_request(
    encryption_key: bytes,
) -> None:
    record_key = "permission:create-invitation:actor:request"
    fingerprint = "request-fingerprint"
    url = "/invite/accept?token=secret-value"

    encrypted = _encrypt_invitation_url(encryption_key, record_key, fingerprint, url)

    assert url not in str(encrypted)
    assert (
        _decrypt_invitation_url(encryption_key, record_key, fingerprint, encrypted)
        == url
    )
    with pytest.raises(IdempotencyConflictError):
        _decrypt_invitation_url(
            encryption_key, record_key, "different-fingerprint", encrypted
        )
    with pytest.raises(IdempotencyConflictError):
        _decrypt_invitation_url(os.urandom(32), record_key, fingerprint, encrypted)
