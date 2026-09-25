from __future__ import annotations

import json
from typing import Any
from uuid import UUID

from app_core.comments.domain import (
    Comment,
    CommentThread,
    CommentThreadNotFoundError,
    CommentThreadStatus,
    CommentThreadTransition,
    ResolvedCommentThreadError,
    validate_thread_transition,
)
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


class PostgresCommentsRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def save(self, comment: Comment) -> Comment:
        await self._session.execute(
            text(
                "INSERT INTO collab.comment_threads "
                "(thread_id,resource_id,anchor_type,node_id,status,created_by) "
                "VALUES (:tid,:rid,:anchor_type,:node_id,'Open',:aid)"
            ),
            {
                "tid": comment.thread_id,
                "rid": comment.resource_id,
                "anchor_type": _anchor_type(comment.anchor),
                "node_id": _anchor_node_id(comment.anchor),
                "aid": comment.author_account_id,
            },
        )
        row = (
            (
                await self._session.execute(
                    text(
                        "INSERT INTO collab.resource_comments "
                        "(comment_id,thread_id,resource_id,author_account_id,"
                        "anchor,body,deleted) "
                        "VALUES (:cid,:tid,:rid,:aid,:anchor,:body,:deleted) "
                        "RETURNING *"
                    ),
                    {
                        "cid": comment.comment_id,
                        "tid": comment.thread_id,
                        "rid": comment.resource_id,
                        "aid": comment.author_account_id,
                        "anchor": json.dumps(comment.anchor, default=str),
                        "body": comment.body,
                        "deleted": comment.deleted,
                    },
                )
            )
            .mappings()
            .one()
        )
        return _to_comment(row)

    async def reply(self, comment: Comment) -> Comment:
        thread = (
            (
                await self._session.execute(
                    text(
                        "SELECT status FROM collab.comment_threads "
                        "WHERE thread_id=:tid AND resource_id=:rid FOR UPDATE"
                    ),
                    {"tid": comment.thread_id, "rid": comment.resource_id},
                )
            )
            .mappings()
            .one_or_none()
        )
        if thread is None:
            raise CommentThreadNotFoundError("comment thread not found")
        if CommentThreadStatus(thread["status"]) is CommentThreadStatus.RESOLVED:
            raise ResolvedCommentThreadError("resolved comment thread must be reopened")
        row = (
            (
                await self._session.execute(
                    text(
                        "INSERT INTO collab.resource_comments "
                        "(comment_id,thread_id,resource_id,author_account_id,"
                        "anchor,body,deleted) "
                        "VALUES (:cid,:tid,:rid,:aid,:anchor,:body,:deleted) "
                        "RETURNING *"
                    ),
                    {
                        "cid": comment.comment_id,
                        "tid": comment.thread_id,
                        "rid": comment.resource_id,
                        "aid": comment.author_account_id,
                        "anchor": json.dumps(comment.anchor, default=str),
                        "body": comment.body,
                        "deleted": comment.deleted,
                    },
                )
            )
            .mappings()
            .one()
        )
        return _to_comment(row)

    async def list_by_resource(self, resource_id: UUID) -> list[Comment]:
        rows = (
            (
                await self._session.execute(
                    text(
                        "SELECT c.*, t.status AS thread_status, "
                        "t.created_by AS thread_created_by, "
                        "t.resolved_at AS thread_resolved_at, "
                        "t.resolved_by AS thread_resolved_by "
                        "FROM collab.resource_comments c "
                        "JOIN collab.comment_threads t "
                        "ON t.resource_id=c.resource_id AND t.thread_id=c.thread_id "
                        "WHERE c.resource_id=:rid AND c.deleted=FALSE "
                        "ORDER BY c.created_at ASC"
                    ),
                    {"rid": resource_id},
                )
            )
            .mappings()
            .all()
        )
        return [_to_comment(r) for r in rows]

    async def find_by_id(self, comment_id: UUID) -> Comment | None:
        row = (
            (
                await self._session.execute(
                    text("SELECT * FROM collab.resource_comments WHERE comment_id=:id"),
                    {"id": comment_id},
                )
            )
            .mappings()
            .one_or_none()
        )
        return None if row is None else _to_comment(row)

    async def find_thread(
        self, resource_id: UUID, thread_id: UUID
    ) -> CommentThread | None:
        row = (
            (
                await self._session.execute(
                    text(
                        "SELECT * FROM collab.comment_threads "
                        "WHERE resource_id=:rid AND thread_id=:tid"
                    ),
                    {"rid": resource_id, "tid": thread_id},
                )
            )
            .mappings()
            .one_or_none()
        )
        return None if row is None else _to_thread(row)

    async def set_thread_status(
        self,
        resource_id: UUID,
        thread_id: UUID,
        status: CommentThreadStatus,
        actor_id: UUID,
    ) -> CommentThreadTransition:
        row = (
            (
                await self._session.execute(
                    text(
                        "SELECT * FROM collab.comment_threads "
                        "WHERE resource_id=:rid AND thread_id=:tid FOR UPDATE"
                    ),
                    {"rid": resource_id, "tid": thread_id},
                )
            )
            .mappings()
            .one_or_none()
        )
        if row is None:
            raise CommentThreadNotFoundError("comment thread not found")
        thread = _to_thread(row)
        changed = validate_thread_transition(thread, status)
        if not changed:
            return CommentThreadTransition(thread=thread, changed=False)
        if status is CommentThreadStatus.RESOLVED:
            updated = (
                (
                    await self._session.execute(
                        text(
                            "UPDATE collab.comment_threads SET status=:status, "
                            "resolved_at=now(), resolved_by=:actor_id "
                            "WHERE resource_id=:rid AND thread_id=:tid RETURNING *"
                        ),
                        {
                            "status": status.value,
                            "actor_id": actor_id,
                            "tid": thread_id,
                            "rid": resource_id,
                        },
                    )
                )
                .mappings()
                .one()
            )
        else:
            updated = (
                (
                    await self._session.execute(
                        text(
                            "UPDATE collab.comment_threads SET status=:status, "
                            "resolved_at=NULL, resolved_by=NULL "
                            "WHERE resource_id=:rid AND thread_id=:tid RETURNING *"
                        ),
                        {
                            "status": status.value,
                            "rid": resource_id,
                            "tid": thread_id,
                        },
                    )
                )
                .mappings()
                .one()
            )
        return CommentThreadTransition(thread=_to_thread(updated), changed=True)

    async def update_body(self, comment_id: UUID, body: str) -> None:
        await self._session.execute(
            text(
                "UPDATE collab.resource_comments SET body=:body, updated_at=now() "
                "WHERE comment_id=:id"
            ),
            {"body": body, "id": comment_id},
        )

    async def mark_deleted(self, comment_id: UUID) -> None:
        await self._session.execute(
            text(
                "UPDATE collab.resource_comments SET deleted=TRUE, updated_at=now() "
                "WHERE comment_id=:id"
            ),
            {"id": comment_id},
        )


def _to_comment(row: Any) -> Comment:
    thread_status = row.get("thread_status")
    return Comment(
        comment_id=row["comment_id"],
        thread_id=row["thread_id"],
        resource_id=row["resource_id"],
        author_account_id=row["author_account_id"],
        anchor=dict(row["anchor"]),
        body=row["body"],
        deleted=bool(row["deleted"]),
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        thread_status=(
            CommentThreadStatus(thread_status) if thread_status is not None else None
        ),
        thread_created_by=row.get("thread_created_by"),
        thread_resolved_at=row.get("thread_resolved_at"),
        thread_resolved_by=row.get("thread_resolved_by"),
    )


def _to_thread(row: Any) -> CommentThread:
    return CommentThread(
        thread_id=row["thread_id"],
        resource_id=row["resource_id"],
        created_by=row["created_by"],
        status=CommentThreadStatus(row["status"]),
        created_at=row["created_at"],
        resolved_at=row["resolved_at"],
        resolved_by=row["resolved_by"],
    )


def _anchor_type(anchor: dict[str, Any]) -> str:
    value = anchor.get("type", "ResourceAnchor")
    if value in {"Node", "NodeAnchor"}:
        return "Node"
    if value in {"TextRange", "TextRangeAnchor"}:
        return "TextRange"
    return "Resource"


def _anchor_node_id(anchor: dict[str, Any]) -> UUID | None:
    value = anchor.get("nodeId")
    return UUID(str(value)) if value else None
