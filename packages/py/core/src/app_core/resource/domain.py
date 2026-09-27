from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Any
from uuid import UUID

from app_core.common.exceptions import ConflictError

RESOURCE_TYPES = ("document", "code", "markdown", "text")


class ResourceLifecycle(StrEnum):
    ACTIVE = "Active"
    TRASHED = "Trashed"
    PURGING = "Purging"
    PURGED = "Purged"


class ResourceError(Exception):
    """Base for resource domain errors."""


class ResourceNotFoundError(ResourceError):
    pass


class ResourceNameConflictError(ResourceError):
    pass


class ResourceTypeImmutableError(ResourceError):
    pass


class DuplicateJournalSeqError(ResourceError):
    pass


class JournalSequenceConflictError(ConflictError):
    def __init__(self, next_sequence: int) -> None:
        super().__init__(
            "The Resource journal changed before this update was accepted.",
            "RESOURCE_JOURNAL_SEQUENCE_CONFLICT",
        )
        self.next_sequence = next_sequence


class ResourcePermissionDeniedError(ResourceError):
    pass


class InvalidResourceNameError(ResourceError):
    pass


@dataclass(frozen=True)
class Resource:
    resource_id: UUID
    project_id: UUID
    folder_id: UUID | None
    resource_type: str
    name: str
    normalized_name: str
    lifecycle: ResourceLifecycle
    schema_version: str = "1.0.0"
    created_by: UUID | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
    trashed_at: datetime | None = None

    def requires_owner_scope(self) -> bool:
        return True


@dataclass(frozen=True)
class JournalOp:
    resource_id: UUID
    journal_seq: int
    ownership_epoch: int
    update_bytes: bytes
    update_hash: str
    accepted_at: datetime | None = None
    durable_at: datetime | None = None

    @classmethod
    def hash_of(cls, update_bytes: bytes) -> str:
        return hashlib.sha256(update_bytes).hexdigest()


@dataclass(frozen=True)
class ResourceContent:
    snapshot: dict[str, Any]
    journal_seq: int


@dataclass(frozen=True)
class ResourceContentMutation:
    journal_seq: int


@dataclass(frozen=True)
class Checkpoint:
    resource_id: UUID
    checkpoint_seq: int
    base_journal_seq: int
    snapshot: dict[str, Any]
    created_at: datetime | None = None


def normalize_resource_name(raw: str) -> str:
    value = raw.strip().casefold()
    if not value:
        raise InvalidResourceNameError("resource name must not be empty")
    return value
