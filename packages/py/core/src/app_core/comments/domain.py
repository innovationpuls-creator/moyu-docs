from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Any
from uuid import UUID


class CommentError(Exception):
    pass


class CommentPermissionDeniedError(CommentError):
    pass


class EmptyCommentBodyError(CommentError):
    pass


class CommentThreadNotFoundError(CommentError):
    pass


class ResolvedCommentThreadError(CommentError):
    pass


class CommentThreadStateConflictError(CommentError):
    pass


class CommentThreadStatus(StrEnum):
    OPEN = "Open"
    RESOLVED = "Resolved"
    DETACHED = "Detached"


@dataclass(frozen=True)
class Comment:
    comment_id: UUID
    thread_id: UUID
    resource_id: UUID
    author_account_id: UUID
    anchor: dict[str, Any]
    body: str
    deleted: bool = False
    created_at: datetime | None = None
    updated_at: datetime | None = None
    thread_status: CommentThreadStatus | None = None
    thread_created_by: UUID | None = None
    thread_resolved_at: datetime | None = None
    thread_resolved_by: UUID | None = None


@dataclass(frozen=True)
class CommentThread:
    thread_id: UUID
    resource_id: UUID
    created_by: UUID
    status: CommentThreadStatus
    created_at: datetime | None = None
    resolved_at: datetime | None = None
    resolved_by: UUID | None = None


@dataclass(frozen=True)
class CommentThreadTransition:
    thread: CommentThread
    changed: bool


def validate_thread_transition(
    thread: CommentThread, target: CommentThreadStatus
) -> bool:
    """Return whether a status change is needed, rejecting invalid transitions."""
    if thread.status == target:
        return False
    if target is CommentThreadStatus.RESOLVED and thread.status in {
        CommentThreadStatus.OPEN,
        CommentThreadStatus.DETACHED,
    }:
        return True
    if (
        target is CommentThreadStatus.OPEN
        and thread.status is CommentThreadStatus.RESOLVED
    ):
        return True
    raise CommentThreadStateConflictError(
        f"cannot transition comment thread from {thread.status} to {target}"
    )
