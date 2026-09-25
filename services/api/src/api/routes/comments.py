from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated
from uuid import UUID

from app_contracts.commands.comments.add_comment import (
    AddComment as AddCommentRequest,
)
from app_contracts.commands.comments.add_comment import AddCommentResponse
from app_contracts.commands.comments.delete_comment import DeleteCommentResponse
from app_contracts.commands.comments.edit_comment import (
    EditComment as EditCommentRequest,
)
from app_contracts.commands.comments.edit_comment import EditCommentResponse
from app_contracts.commands.comments.reopen_comment_thread import (
    ReopenCommentThreadResponse,
)
from app_contracts.commands.comments.resolve_comment_thread import (
    ResolveCommentThreadResponse,
)
from app_contracts.queries.comments.list_comments import (
    Item as CommentListItem,
)
from app_contracts.queries.comments.list_comments import (
    ListCommentsResponse,
)
from app_contracts.queries.comments.list_comments import (
    Status as CommentThreadStatusValue,
)
from app_core.comments.application import AddComment as AddCommentUseCase
from app_core.comments.application import DeleteComment as DeleteCommentUseCase
from app_core.comments.application import EditComment as EditCommentUseCase
from app_core.comments.application import ListComments as ListCommentsUseCase
from app_core.comments.application import (
    ReopenCommentThread as ReopenCommentThreadUseCase,
)
from app_core.comments.application import (
    ResolveCommentThread as ResolveCommentThreadUseCase,
)
from app_core.comments.domain import (
    CommentPermissionDeniedError,
    CommentThreadNotFoundError,
    CommentThreadStateConflictError,
    CommentThreadTransition,
    EmptyCommentBodyError,
    ResolvedCommentThreadError,
)
from app_core.notifications.application import NotifyMentionedUsers
from app_core.session.domain.session import Session
from app_infra.nats.resource_broadcast_publisher import (
    NatsResourceBroadcastPublisher,
)
from app_infra.postgres.comments_repository import PostgresCommentsRepository
from app_infra.postgres.notification_repository import (
    PostgresAccountLookup,
    PostgresNotificationsRepository,
)
from app_infra.postgres.permission_workspace_repository import (
    PostgresWorkspaceMembershipRepository,
)
from app_infra.postgres.project_repository import PostgresProjectRepository
from app_infra.postgres.resource.resource_repository import (
    PostgresResourceRepository,
)
from app_infra.postgres.resource_ownership_repository import (
    PostgresResourceOwnershipRepository,
)
from app_infra.postgres.webhook_enqueuer import (
    enqueue_webhook_events_for_resource,
)
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from api.dependencies.auth import get_current_session, get_db_session
from api.infra.broadcast import BroadcastRelayUnavailable, get_broadcast_publisher

router = APIRouter()


async def _publish_thread_transition(
    publisher: NatsResourceBroadcastPublisher,
    transition: CommentThreadTransition,
    event_type: str,
) -> None:
    if not transition.changed:
        return
    thread = transition.thread
    try:
        await publisher.publish(
            thread.resource_id,
            event_type,
            {
                "threadId": str(thread.thread_id),
                "resourceId": str(thread.resource_id),
                "status": thread.status.value,
                "resolvedBy": str(thread.resolved_by)
                if thread.resolved_by is not None
                else None,
                "resolvedAt": thread.resolved_at.isoformat()
                if thread.resolved_at is not None
                else None,
            },
        )
    except BroadcastRelayUnavailable:
        __import__("logging").getLogger("dom.api.comments").warning(
            "comment relay unavailable; thread transition persisted without event"
        )


@router.post(
    "/resources/{resource_id}/comments",
    response_model=AddCommentResponse,
    status_code=201,
)
async def add_comment(
    resource_id: UUID,
    body: AddCommentRequest,
    current: Annotated[Session, Depends(get_current_session)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
    publisher: Annotated[
        NatsResourceBroadcastPublisher, Depends(get_broadcast_publisher)
    ],
) -> AddCommentResponse:
    use_case = AddCommentUseCase(
        PostgresCommentsRepository(session),
        PostgresResourceOwnershipRepository(session),
    )
    try:
        comment = await use_case.execute(
            current.account_id,
            resource_id,
            body=body.body,
            thread_id=body.threadId,
            anchor=dict(body.anchor) if body.anchor is not None else None,
        )
    except ResolvedCommentThreadError:
        raise HTTPException(status_code=409, detail="COMMENT_THREAD_RESOLVED")
    except CommentThreadNotFoundError:
        raise HTTPException(status_code=404, detail="COMMENT_THREAD_NOT_FOUND")
    except CommentPermissionDeniedError:
        raise HTTPException(status_code=403, detail="RESOURCE_PERMISSION_DENIED")
    except EmptyCommentBodyError:
        raise HTTPException(status_code=400, detail="COMMENT_BODY_INVALID")
    except LookupError:
        raise HTTPException(status_code=404, detail="RESOURCE_NOT_FOUND")
    # Mentions (arch 17): @具体用户 -> in-app notifications for recipients who
    # already hold resource.read (mention never grants permission).
    await NotifyMentionedUsers(
        PostgresNotificationsRepository(session),
        PostgresAccountLookup(session),
        PostgresResourceRepository(session),
        PostgresProjectRepository(session),
        PostgresWorkspaceMembershipRepository(session),
    ).execute(
        current.account_id,
        resource_id,
        comment.comment_id,
        comment.body,
    )
    # Webhooks (arch 10): enqueue webhook.deliver for every Active
    # subscription of the resource's workspace. Best-effort: the comment write
    # never depends on the event queue.
    try:
        await enqueue_webhook_events_for_resource(
            session, resource_id, "comment.posted"
        )
    except Exception:
        __import__("logging").getLogger("dom.api.comments").warning(
            "webhook enqueue skipped for comment"
        )
    # Realtime (arch 17): comment events ride the resource broadcast subject.
    # Delivery is BEST-EFFORT: the comment itself is a durable DB write and must
    # never depend on the relay; a relay outage only delays live panels (logged).
    try:
        await publisher.publish(
            resource_id,
            "comment.added",
            {
                "resourceId": str(resource_id),
                "commentId": str(comment.comment_id),
                "threadId": str(comment.thread_id),
                "author": str(comment.author_account_id),
                "body": comment.body,
            },
        )
    except BroadcastRelayUnavailable:
        __import__("logging").getLogger("dom.api.comments").warning(
            "comment relay unavailable; comment persisted without event"
        )
    return AddCommentResponse(
        commentId=comment.comment_id,
        threadId=comment.thread_id,
        body=comment.body,
        createdAt=comment.created_at or datetime.now(UTC),
    )


@router.get("/resources/{resource_id}/comments", response_model=ListCommentsResponse)
async def list_comments(
    resource_id: UUID,
    current: Annotated[Session, Depends(get_current_session)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> ListCommentsResponse:
    use_case = ListCommentsUseCase(
        PostgresCommentsRepository(session),
        PostgresResourceOwnershipRepository(session),
    )
    if await PostgresResourceRepository(session).get(resource_id) is None:
        raise HTTPException(status_code=404, detail="RESOURCE_NOT_FOUND")
    try:
        comments = await use_case.execute(current.account_id, resource_id)
    except CommentPermissionDeniedError:
        raise HTTPException(status_code=403, detail="RESOURCE_PERMISSION_DENIED")
    items: list[CommentListItem] = []
    for comment in comments:
        if comment.thread_status is None or comment.thread_created_by is None:
            raise RuntimeError("comment list projection is missing thread state")
        items.append(
            CommentListItem(
                commentId=comment.comment_id,
                threadId=comment.thread_id,
                authorAccountId=comment.author_account_id,
                body=comment.body,
                anchor=comment.anchor,
                createdAt=comment.created_at or datetime.now(UTC),
                status=CommentThreadStatusValue(comment.thread_status.value),
                createdBy=comment.thread_created_by,
                resolvedAt=comment.thread_resolved_at,
                resolvedBy=comment.thread_resolved_by,
            )
        )
    return ListCommentsResponse(resourceId=resource_id, items=items)


@router.patch("/comments/{comment_id}", response_model=EditCommentResponse)
async def edit_comment(
    comment_id: UUID,
    body: EditCommentRequest,
    current: Annotated[Session, Depends(get_current_session)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
    publisher: Annotated[
        NatsResourceBroadcastPublisher, Depends(get_broadcast_publisher)
    ],
) -> EditCommentResponse:
    use_case = EditCommentUseCase(
        PostgresCommentsRepository(session),
        PostgresResourceOwnershipRepository(session),
    )
    try:
        comment = await use_case.execute(current.account_id, comment_id, body.body)
    except CommentPermissionDeniedError:
        raise HTTPException(status_code=403, detail="COMMENT_PERMISSION_DENIED")
    except EmptyCommentBodyError:
        raise HTTPException(status_code=400, detail="COMMENT_BODY_INVALID")
    except LookupError:
        raise HTTPException(status_code=404, detail="COMMENT_NOT_FOUND")
    try:
        await publisher.publish(
            comment.resource_id,
            "comment.edited",
            {"commentId": str(comment.comment_id), "body": comment.body},
        )
    except BroadcastRelayUnavailable:
        __import__("logging").getLogger("dom.api.comments").warning(
            "comment relay unavailable; edit persisted without event"
        )
    return EditCommentResponse(commentId=comment.comment_id, body=comment.body)


@router.delete("/comments/{comment_id}", response_model=DeleteCommentResponse)
async def delete_comment(
    comment_id: UUID,
    current: Annotated[Session, Depends(get_current_session)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
    publisher: Annotated[
        NatsResourceBroadcastPublisher, Depends(get_broadcast_publisher)
    ],
) -> DeleteCommentResponse:
    use_case = DeleteCommentUseCase(
        PostgresCommentsRepository(session),
        PostgresResourceOwnershipRepository(session),
    )
    try:
        comment = await use_case.execute(current.account_id, comment_id)
    except CommentPermissionDeniedError:
        raise HTTPException(status_code=403, detail="COMMENT_PERMISSION_DENIED")
    except LookupError:
        raise HTTPException(status_code=404, detail="COMMENT_NOT_FOUND")
    try:
        await publisher.publish(
            comment.resource_id,
            "comment.deleted",
            {"commentId": str(comment.comment_id)},
        )
    except BroadcastRelayUnavailable:
        __import__("logging").getLogger("dom.api.comments").warning(
            "comment relay unavailable; delete persisted without event"
        )
    return DeleteCommentResponse(commentId=comment.comment_id, deleted=True)


@router.post(
    "/resources/{resource_id}/comments/threads/{thread_id}/resolve",
    response_model=ResolveCommentThreadResponse,
)
async def resolve_comment_thread(
    resource_id: UUID,
    thread_id: UUID,
    current: Annotated[Session, Depends(get_current_session)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
    publisher: Annotated[
        NatsResourceBroadcastPublisher, Depends(get_broadcast_publisher)
    ],
) -> ResolveCommentThreadResponse:
    use_case = ResolveCommentThreadUseCase(
        PostgresCommentsRepository(session),
        PostgresResourceOwnershipRepository(session),
    )
    try:
        transition = await use_case.execute(current.account_id, resource_id, thread_id)
    except CommentThreadNotFoundError:
        raise HTTPException(status_code=404, detail="COMMENT_THREAD_NOT_FOUND")
    except CommentPermissionDeniedError:
        raise HTTPException(status_code=403, detail="COMMENT_PERMISSION_DENIED")
    except CommentThreadStateConflictError:
        raise HTTPException(status_code=409, detail="COMMENT_THREAD_STATE_CONFLICT")
    await session.commit()
    await _publish_thread_transition(publisher, transition, "ThreadResolved")
    return ResolveCommentThreadResponse.model_validate(
        _thread_transition_payload(transition)
    )


@router.post(
    "/resources/{resource_id}/comments/threads/{thread_id}/reopen",
    response_model=ReopenCommentThreadResponse,
)
async def reopen_comment_thread(
    resource_id: UUID,
    thread_id: UUID,
    current: Annotated[Session, Depends(get_current_session)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
    publisher: Annotated[
        NatsResourceBroadcastPublisher, Depends(get_broadcast_publisher)
    ],
) -> ReopenCommentThreadResponse:
    use_case = ReopenCommentThreadUseCase(
        PostgresCommentsRepository(session),
        PostgresResourceOwnershipRepository(session),
    )
    try:
        transition = await use_case.execute(current.account_id, resource_id, thread_id)
    except CommentThreadNotFoundError:
        raise HTTPException(status_code=404, detail="COMMENT_THREAD_NOT_FOUND")
    except CommentPermissionDeniedError:
        raise HTTPException(status_code=403, detail="COMMENT_PERMISSION_DENIED")
    except CommentThreadStateConflictError:
        raise HTTPException(status_code=409, detail="COMMENT_THREAD_STATE_CONFLICT")
    await session.commit()
    await _publish_thread_transition(publisher, transition, "ThreadReopened")
    return ReopenCommentThreadResponse.model_validate(
        _thread_transition_payload(transition)
    )


def _thread_transition_payload(
    transition: CommentThreadTransition,
) -> dict[str, str | None]:
    thread = transition.thread
    return {
        "threadId": str(thread.thread_id),
        "resourceId": str(thread.resource_id),
        "status": thread.status.value,
        "resolvedAt": thread.resolved_at.isoformat()
        if thread.resolved_at is not None
        else None,
        "resolvedBy": str(thread.resolved_by)
        if thread.resolved_by is not None
        else None,
    }
