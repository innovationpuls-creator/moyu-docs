from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Protocol
from uuid import UUID

PURGE_EFFECT_KEY_PREFIX = "lifecycle.purge.workspace:"


class PurgeDisposition(StrEnum):
    PURGED = "Purged"
    ALREADY_PURGED = "AlreadyPurged"
    MISSING = "Missing"


@dataclass(frozen=True)
class PurgeCandidate:
    workspace_id: UUID
    purge_eligible_at: datetime


@dataclass(frozen=True)
class PurgeResult:
    workspace_id: UUID
    disposition: PurgeDisposition
    deleted_projects: int = 0
    deleted_folders: int = 0


class WorkspacePurgeRepository(Protocol):
    async def candidates_before(
        self, now: datetime, limit: int
    ) -> list[PurgeCandidate]: ...
    async def get_for_purge(self, workspace_id: UUID) -> PurgeCandidate | None: ...
    async def purge_workspace(self, workspace_id: UUID) -> PurgeResult: ...


class WorkspaceMembershipCleanupPort(Protocol):
    async def remove_workspace_memberships(self, workspace_id: UUID) -> None: ...


def purge_effect_key(workspace_id: UUID) -> str:
    return f"{PURGE_EFFECT_KEY_PREFIX}{workspace_id}"
