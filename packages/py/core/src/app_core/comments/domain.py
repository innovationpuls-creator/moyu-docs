from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID


class CommentError(Exception):
    pass


class CommentPermissionDeniedError(CommentError):
    pass


class EmptyCommentBodyError(CommentError):
    pass


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
