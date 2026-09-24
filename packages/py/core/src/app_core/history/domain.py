from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from uuid import UUID


class VersionKind(StrEnum):
    AUTOMATIC = "Automatic"
    NAMED = "Named"
    RESTORE = "Restore"


class HistoryError(Exception):
    pass


class NamedVersionLabelConflictError(HistoryError):
    pass


@dataclass(frozen=True)
class VersionNode:
    """A user-visible history node (aggregated FROM checkpoints/journal)."""

    node_id: UUID
    resource_id: UUID
    kind: VersionKind
    label: str | None
    author: UUID | None
    occurred_at: datetime | None
    base_journal_seq: int
    op_count: int = 0
    summary: str | None = None


@dataclass(frozen=True)
class NamedVersion:
    version_id: UUID
    resource_id: UUID
    label: str
    base_journal_seq: int
    created_by: UUID | None
    created_at: datetime | None
