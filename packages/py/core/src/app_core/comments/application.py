from __future__ import annotations

from typing import Any
from uuid import UUID, uuid4

from app_core.comments.domain import (
    Comment,
    CommentPermissionDeniedError,
    EmptyCommentBodyError,
)
from app_core.comments.ports import CommentsRepository
from app_core.resource.ports import ReadOnlyResourceOwnershipPort


class AddComment:
    """Arch 17 §8: one flat-thread comment on a Resource."""

    def __init__(
        self,
        comments: CommentsRepository,
        ownership: ReadOnlyResourceOwnershipPort,
    ) -> None:
        self._comments = comments
        self._ownership = ownership

    async def execute(
        self,
        actor_id: UUID,
        resource_id: UUID,
        *,
        body: str,
        thread_id: UUID | None = None,
        anchor: dict[str, Any] | None = None,
    ) -> Comment:
        if not body.strip():
            raise EmptyCommentBodyError("comment body must not be empty")
        if not await self._ownership.authorize(actor_id, resource_id, "resource.read"):
            raise CommentPermissionDeniedError("no resource.read permission to comment")
        comment = Comment(
            comment_id=uuid4(),
            thread_id=thread_id or uuid4(),
            resource_id=resource_id,
            author_account_id=actor_id,
            anchor=anchor or {"type": "ResourceAnchor"},
            body=body,
        )
        return await self._comments.save(comment)


class ListComments:
    def __init__(self, comments: CommentsRepository) -> None:
        self._comments = comments

    async def execute(self, resource_id: UUID) -> list[Comment]:
        return await self._comments.list_by_resource(resource_id)


class EditComment:
    """Authors-only edit; the body must stay non-empty (FR-CMT-003)."""

    def __init__(
        self, comments: CommentsRepository, ownership: ReadOnlyResourceOwnershipPort
    ) -> None:
        self._comments = comments
        self._ownership = ownership

    async def execute(self, actor_id: UUID, comment_id: UUID, body: str) -> Comment:
        if not body.strip():
            raise EmptyCommentBodyError("body must not be empty")
        comment = await self._comments.find_by_id(comment_id)
        if comment is None:
            raise LookupError("comment not found")
        if not await self._ownership.authorize(
            actor_id, comment.resource_id, "resource.read"
        ):
            raise CommentPermissionDeniedError("no resource.read permission")
        if comment.author_account_id != actor_id:
            raise CommentPermissionDeniedError("only the author may edit")
        if comment.deleted:
            raise LookupError("comment not found")
        await self._comments.update_body(comment_id, body)
        return Comment(
            comment_id=comment.comment_id,
            thread_id=comment.thread_id,
            resource_id=comment.resource_id,
            author_account_id=comment.author_account_id,
            anchor=comment.anchor,
            body=body,
        )


class DeleteComment:
    """Authors-only soft delete: the row stays (thread integrity), listing
    hides deleted comments (FR-CMT-004)."""

    def __init__(
        self, comments: CommentsRepository, ownership: ReadOnlyResourceOwnershipPort
    ) -> None:
        self._comments = comments
        self._ownership = ownership

    async def execute(self, actor_id: UUID, comment_id: UUID) -> Comment:
        comment = await self._comments.find_by_id(comment_id)
        if comment is None or comment.deleted:
            raise LookupError("comment not found")
        if not await self._ownership.authorize(
            actor_id, comment.resource_id, "resource.read"
        ):
            raise CommentPermissionDeniedError("no resource.read permission")
        if comment.author_account_id != actor_id:
            raise CommentPermissionDeniedError("only the author may delete")
        await self._comments.mark_deleted(comment_id)
        return Comment(
            comment_id=comment.comment_id,
            thread_id=comment.thread_id,
            resource_id=comment.resource_id,
            author_account_id=comment.author_account_id,
            anchor=comment.anchor,
            body=comment.body,
            deleted=True,
        )
