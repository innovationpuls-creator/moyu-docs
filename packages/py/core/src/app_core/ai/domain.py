from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Any
from uuid import UUID


class ChangesetError(Exception):
    pass


class ChangesetStatus(StrEnum):
    PROPOSED = "Proposed"
    APPLIED = "Applied"
    REJECTED = "Rejected"


@dataclass(frozen=True)
class ChangeSet:
    changeset_id: UUID
    resource_id: UUID
    instruction: str
    ops: list[dict[str, Any]]
    status: ChangesetStatus = ChangesetStatus.PROPOSED
    task_id: UUID | None = None
    created_by: UUID | None = None
    created_at: datetime | None = None
    applied_at: datetime | None = None
