from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timedelta
from uuid import UUID

from app_core.common.exceptions import (
    AuthenticationError,
    ConflictError,
    NotFoundError,
    ValidationError,
)


class RequestAccountDeletion:
    def __init__(
        self,
        accounts,
        sessions,
        ownership,
        audit,
        schedule,
        *,
        now: Callable[[], datetime],
    ) -> None:
        (
            self.accounts,
            self.sessions,
            self.ownership,
            self.audit,
            self.schedule,
            self.now,
        ) = accounts, sessions, ownership, audit, schedule, now

    async def execute(self, account_id: UUID, session_id: UUID) -> None:
        record = await self.accounts.find_by_account_id(account_id)
        session = await self.sessions.find_by_id(session_id)
        now = self.now()
        if record is None or session is None:
            raise AuthenticationError(
                "SESSION_NOT_AUTHORIZED", "SESSION_NOT_AUTHORIZED"
            )
        if session.account_id != account_id or not session.is_active(now):
            raise AuthenticationError(
                "SESSION_NOT_AUTHORIZED", "SESSION_NOT_AUTHORIZED"
            )
        if not session.has_recent_reauthentication(now):
            raise AuthenticationError(
                "RECENT_AUTHENTICATION_REQUIRED", "RECENT_AUTHENTICATION_REQUIRED"
            )
        is_sole, workspace_name = await self.ownership.has_sole_workspace_ownership(
            account_id
        )
        if is_sole:
            raise ConflictError(
                _sole_owner_message(workspace_name), "ACCOUNT_DELETION_SOLE_OWNER"
            )
        if record.account.status.value == "DeletionPending":
            return
        record.account.request_deletion(now)
        await self.accounts.update(record.account)
        await self.schedule.schedule(account_id, now + timedelta(days=30))
        await self.audit.append(
            actor_type="Account", actor_id=account_id, action="AccountDeletionRequested"
        )


class CancelAccountDeletion:
    def __init__(
        self, accounts, audit, schedule, *, now: Callable[[], datetime]
    ) -> None:
        self.accounts, self.audit, self.schedule, self.now = (
            accounts,
            audit,
            schedule,
            now,
        )

    async def execute(self, account_id: UUID) -> None:
        record = await self.accounts.find_by_account_id(account_id)
        if record is None:
            raise NotFoundError("ACCOUNT_NOT_FOUND", "ACCOUNT_NOT_FOUND")
        record.account.cancel_deletion(self.now())
        await self.accounts.update(record.account)
        cancelled = await self.schedule.cancel(account_id, self.now())
        if cancelled:
            await self.audit.append(
                actor_type="Account",
                actor_id=account_id,
                action="AccountDeletionCancelled",
            )


class ProcessAccountPurge:
    def __init__(
        self, accounts, sessions, audit, deletion, *, now: Callable[[], datetime]
    ) -> None:
        self.accounts, self.sessions, self.audit, self.deletion, self.now = (
            accounts,
            sessions,
            audit,
            deletion,
            now,
        )

    async def execute(self, account_id: UUID) -> None:
        record = await self.accounts.find_by_account_id(account_id)
        if record is None or record.account.deletion_requested_at is None:
            raise ValidationError("PURGE_NOT_DUE", "PURGE_NOT_DUE")
        now = self.now()
        if now < record.account.deletion_requested_at + timedelta(days=30):
            raise ValidationError("PURGE_NOT_DUE", "PURGE_NOT_DUE")
        record.account.purge(now)
        await self.accounts.update(record.account)
        await self.sessions.revoke_all_sessions(account_id, "AccountDeleted")
        await self.audit.append(
            actor_type="Account", actor_id=account_id, action="AccountDeleted"
        )
        await self.deletion.complete(account_id, now)


def _sole_owner_message(workspace_name: str | None) -> str:
    if workspace_name:
        return (
            f"您是工作区 {workspace_name} 的唯一所有者，"
            "请先转让所有权或解散工作区后再申请注销账号"
        )
    return (
        "您是某个未删除工作区的唯一所有者，请先转让所有权或解散工作区后再申请注销账号"
    )
