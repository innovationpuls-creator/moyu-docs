"""Per-Resource physical purge (arch 09 §retention, arch 25).

A Trashed Resource becomes eligible after the retention window; purging
physically deletes the Resource and its dependent rows (journal, checkpoints,
named versions, ownership, assets, comments, search index, ai changesets) in
one transaction. The frozen rule (sibling names stay reserved until physical
cleanup) is satisfied: the purge IS the cleanup.
"""

from __future__ import annotations

from typing import Protocol
from uuid import UUID

FATAL_PURGE_MESSAGE = "resource purge failed irrecoverably"


class RetryablePurgeError(Exception):
    pass


class FatalPurgeError(Exception):
    pass


def purge_effect_key(resource_id: UUID) -> str:
    return f"resource.purge:{resource_id}"


class ResourcePurgeRepository(Protocol):
    async def purge_resource(self, resource_id: UUID) -> bool: ...


class PurgeResource:
    def __init__(self, purge: ResourcePurgeRepository) -> None:
        self._purge = purge

    async def execute(self, resource_id: UUID) -> bool:
        try:
            return await self._purge.purge_resource(resource_id)
        except Exception as exc:
            raise RetryablePurgeError(str(exc)) from exc
