from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import StrEnum
from uuid import UUID, uuid4

from app_core.common.exceptions import AuthenticationError


class AccountStatus(StrEnum):
    PENDING_VERIFICATION = "PendingVerification"
    ACTIVE = "Active"
    DISABLED = "Disabled"
    DELETION_PENDING = "DeletionPending"
    DELETED = "Deleted"


@dataclass
class Account:
    account_id: UUID
    primary_email: str
    normalized_email: str
    status: AccountStatus
    created_at: datetime
    updated_at: datetime
    email_verified_at: datetime | None = None
    deletion_requested_at: datetime | None = None
    pre_deletion_status: AccountStatus | None = None

    @classmethod
    def create_with_email(cls, email: str, at: datetime | None = None) -> Account:
        primary_email = email.strip()
        now = at or _utc_now()
        return cls(
            account_id=uuid4(),
            primary_email=primary_email,
            normalized_email=primary_email.casefold(),
            status=AccountStatus.PENDING_VERIFICATION,
            created_at=now,
            updated_at=now,
        )

    def can_enter_product(self) -> bool:
        return self.status in {
            AccountStatus.PENDING_VERIFICATION,
            AccountStatus.ACTIVE,
            AccountStatus.DELETION_PENDING,
        }

    def can_create_workspace(self) -> bool:
        return self.status is AccountStatus.ACTIVE

    def can_login(self) -> bool:
        return self.status in {
            AccountStatus.PENDING_VERIFICATION,
            AccountStatus.ACTIVE,
            AccountStatus.DELETION_PENDING,
        }

    def is_in_recovery_mode(self) -> bool:
        return self.status is AccountStatus.DELETION_PENDING

    def verify_email(self, at: datetime | None = None) -> None:
        if self.status in {
            AccountStatus.DISABLED,
            AccountStatus.DELETION_PENDING,
            AccountStatus.DELETED,
        }:
            raise AuthenticationError(
                "Account cannot verify email in its current state."
            )
        self.status = AccountStatus.ACTIVE
        self.email_verified_at = at or _utc_now()
        self.updated_at = self.email_verified_at

    def disable(self, at: datetime | None = None) -> None:
        self.status = AccountStatus.DISABLED
        self.updated_at = at or _utc_now()

    def request_deletion(self, at: datetime | None = None) -> None:
        if self.status in {AccountStatus.DISABLED, AccountStatus.DELETED}:
            raise AuthenticationError(
                "Account cannot request deletion in its current state."
            )
        if self.status is AccountStatus.DELETION_PENDING:
            return
        now = at or _utc_now()
        self.pre_deletion_status = self.status
        self.deletion_requested_at = now
        self.status = AccountStatus.DELETION_PENDING
        self.updated_at = now

    def cancel_deletion(self, at: datetime | None = None) -> None:
        if self.status is not AccountStatus.DELETION_PENDING:
            return
        now = at or _utc_now()
        self.status = self.pre_deletion_status or AccountStatus.ACTIVE
        self.pre_deletion_status = None
        self.deletion_requested_at = None
        self.updated_at = now

    def purge(self, at: datetime | None = None) -> None:
        self.status = AccountStatus.DELETED
        self.updated_at = at or _utc_now()


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)
