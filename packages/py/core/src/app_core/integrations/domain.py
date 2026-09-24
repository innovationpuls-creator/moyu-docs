from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from uuid import UUID

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)

REPLAY_WINDOW_SECONDS = 300
MAX_PAYLOAD_BYTES = 8192


class IntegrationError(Exception):
    pass


def _signed_message(payload: bytes, timestamp: datetime) -> bytes:
    truncated = payload[:MAX_PAYLOAD_BYTES]
    return truncated + b"|" + str(int(timestamp.timestamp())).encode()


@dataclass(frozen=True)
class IntegrationKey:
    key_id: UUID
    account_id: UUID
    label: str
    created_at: datetime | None = None
    revoked: bool = False


def new_keypair() -> tuple[bytes, str]:
    """Returns (private_key_bytes, public_key_hex); ONLY the public key is
    stored server-side (arch 20 signature model)."""
    private = Ed25519PrivateKey.generate()
    public_hex = private.public_key().public_bytes_raw().hex()
    return private.private_bytes_raw(), public_hex


def public_from_private(private_key: bytes) -> str:
    """Derive the public key hex from the stored private seed (webhook
    signing uses the same keypair as integration keys, arch 20 model)."""
    return (
        Ed25519PrivateKey.from_private_bytes(private_key)
        .public_key()
        .public_bytes_raw()
        .hex()
    )


def sign(payload: bytes, timestamp: datetime, private_key: bytes) -> str:
    key = Ed25519PrivateKey.from_private_bytes(private_key)
    return key.sign(_signed_message(payload, timestamp)).hex()


def verify(
    payload: bytes,
    timestamp: datetime,
    signature: str,
    public_key_hex: str,
    *,
    now: datetime | None = None,
) -> bool:
    current = now or datetime.now(timezone.utc)
    if abs((current - timestamp).total_seconds()) > REPLAY_WINDOW_SECONDS:
        return False
    try:
        public = Ed25519PublicKey.from_public_bytes(bytes.fromhex(public_key_hex))
        public.verify(bytes.fromhex(signature), _signed_message(payload, timestamp))
        return True
    except (InvalidSignature, ValueError):
        return False
