from __future__ import annotations

import json
from typing import Any
from uuid import UUID

from app_core.comments.domain import Comment
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


class PostgresCommentsRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def save(self, comment: Comment) -> Comment:
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
                        "SELECT * FROM collab.resource_comments "
                        "WHERE resource_id=:rid AND deleted=FALSE "
                        "ORDER BY created_at ASC"
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
    )
