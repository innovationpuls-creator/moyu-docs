from __future__ import annotations

from typing import Protocol

from app_core.account.ports.idempotency_repository import IdempotencyRecord


class WorkspaceIdempotencyPort(Protocol):
    """Idempotency storage bound to a canonical Workspace request fingerprint.

    ``claim`` must atomically insert the key/fingerprint under a unique key so
    concurrent requests cannot both become the claimant.
    """

    async def get(self, key: str) -> IdempotencyRecord | None: ...

    async def get_fingerprint(self, key: str) -> str | None: ...

    async def claim(self, key: str, request_fingerprint: str) -> bool: ...

    async def complete(
        self, key: str, request_fingerprint: str, response: bytes
    ) -> None: ...
