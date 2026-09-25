from __future__ import annotations

from typing import Protocol
from uuid import UUID

from app_core.comments.domain import (
    Comment,
    CommentThread,
    CommentThreadStatus,
    CommentThreadTransition,
)


class CommentsRepository(Protocol):
    """Persistence port for comments and their independent thread lifecycle."""

    # save creates a new thread and its root comment atomically.
    async def save(self, comment: Comment) -> Comment: ...

    # reply appends only to an existing, non-resolved thread.
    async def reply(self, comment: Comment) -> Comment: ...

    async def list_by_resource(self, resource_id: UUID) -> list[Comment]: ...
    async def find_by_id(self, comment_id: UUID) -> Comment | None: ...
    async def find_thread(
        self, resource_id: UUID, thread_id: UUID
    ) -> CommentThread | None: ...
    async def set_thread_status(
        self,
        resource_id: UUID,
        thread_id: UUID,
        status: CommentThreadStatus,
        actor_id: UUID,
    ) -> CommentThreadTransition: ...
    async def update_body(self, comment_id: UUID, body: str) -> None: ...
    async def mark_deleted(self, comment_id: UUID) -> None: ...
