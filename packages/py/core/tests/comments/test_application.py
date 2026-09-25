from __future__ import annotations

from uuid import uuid4

import pytest
from app_core.comments.application import AddComment, ListComments
from app_core.comments.domain import (
    Comment,
    CommentPermissionDeniedError,
    EmptyCommentBodyError,
)
from app_core.comments.ports import CommentsRepository


class _MemoryComments(CommentsRepository):
    def __init__(self) -> None:
        self.rows: list[Comment] = []
        self.list_calls = 0

    async def save(self, comment: Comment) -> Comment:
        self.rows.append(comment)
        return comment

    async def list_by_resource(self, resource_id):
        self.list_calls += 1
        return [c for c in self.rows if c.resource_id == resource_id]


class _Ownership:
    def __init__(self, *, allowed: bool) -> None:
        self.allowed = allowed

    async def authorize(self, actor_id, scope_id, operation) -> bool:
        return self.allowed


@pytest.mark.asyncio
async def test_add_comment_requires_read_access_and_body() -> None:
    comments = _MemoryComments()
    add = AddComment(comments, _Ownership(allowed=False))
    with pytest.raises(CommentPermissionDeniedError):
        await add.execute(uuid4(), uuid4(), body="hi")
    allowed = AddComment(comments, _Ownership(allowed=True))
    with pytest.raises(EmptyCommentBodyError):
        await allowed.execute(uuid4(), uuid4(), body="   ")
    resource_id = uuid4()
    comment = await allowed.execute(uuid4(), resource_id, body="good")
    assert comment.body == "good"
    assert comment.anchor == {"type": "ResourceAnchor"}
    listed = await ListComments(comments, _Ownership(allowed=True)).execute(
        uuid4(), resource_id
    )
    assert [c.comment_id for c in listed] == [comment.comment_id]


@pytest.mark.asyncio
async def test_list_comments_requires_resource_read_before_query() -> None:
    comments = _MemoryComments()
    use_case = ListComments(comments, _Ownership(allowed=False))

    with pytest.raises(CommentPermissionDeniedError):
        await use_case.execute(uuid4(), uuid4())

    assert comments.list_calls == 0
