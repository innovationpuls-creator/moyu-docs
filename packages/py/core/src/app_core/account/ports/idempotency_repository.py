from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol


class IdempotencyState(StrEnum):
    IN_PROGRESS = "InProgress"
    COMPLETED = "Completed"


@dataclass(frozen=True)
class IdempotencyRecord:
    state: IdempotencyState
    response: bytes | None = None


class IdempotencyRepositoryPort(Protocol):
    async def claim(self, key: str) -> bool: ...

    async def get(self, key: str) -> IdempotencyRecord | None: ...

    async def complete(self, key: str, response: bytes) -> None: ...
