from __future__ import annotations

from typing import Any
from uuid import UUID, uuid4

from app_core.common.exceptions import PermissionDeniedError
from app_core.notifications.domain import Notification, extract_mentioned_emails
from app_core.notifications.ports import (
    AccountLookup,
    NotificationsRepository,
)
from app_core.permission.domain.workspace_membership import WorkspaceOperation
from app_core.resource.ports import ResourceRepository


class NotifyMentionedUsers:
    """Arch 17: a comment that @-mentions real users creates in-app
    notifications; mention is notification-only and never grants permission
    (recipients must already hold workspace-membership READ)."""

    def __init__(
        self,
        notifications: NotificationsRepository,
        accounts: AccountLookup,
        resources: ResourceRepository,
        projects: object,
        membership: Any,
    ) -> None:
        self._notifications = notifications
        self._accounts = accounts
        self._resources = resources
        self._projects = projects
        self._membership = membership

    async def execute(
        self,
        author_id: UUID,
        resource_id: UUID,
        comment_id: UUID,
        body: str,
    ) -> int:
        current = await self._resources.get(resource_id)
        if current is None:
            return 0
        project = await self._projects.find_by_id(  # type: ignore[attr-defined]
            current.project_id
        )
        workspace_id = (
            project.workspace_id if project is not None else current.project_id
        )
        mentioned = 0
        for email in extract_mentioned_emails(body):
            account_id = await self._accounts.find_id_by_email(email)
            if account_id is None or account_id == author_id:
                continue
            try:
                await self._membership.authorize(
                    account_id,
                    WorkspaceOperation.READ,
                    workspace_id=workspace_id,
                )
            except PermissionDeniedError:
                continue
            await self._notifications.save(
                Notification(
                    notification_id=uuid4(),
                    account_id=account_id,
                    kind="comment.mention",
                    payload={
                        "resourceId": str(resource_id),
                        "commentId": str(comment_id),
                        "author": str(author_id),
                        "excerpt": body[:120],
                    },
                    target_ref={
                        "resourceId": str(resource_id),
                        "commentId": str(comment_id),
                    },
                    source_event_id=comment_id,
                )
            )
            mentioned += 1
        return mentioned
