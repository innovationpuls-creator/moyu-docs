from __future__ import annotations

from uuid import UUID, uuid4

from app_core.account.domain.account import Account, AccountStatus
from app_core.account.ports.account_repository import AccountRecord
from app_core.common.exceptions import DuplicateEmailError
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession


class PostgresAccountRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def save(self, account: Account, password_hash: str) -> None:
        try:
            await self._save(account, password_hash)
        except IntegrityError as error:
            # A concurrent registration or identity bind won the unique
            # constraint race; the failed statement is rolled back and the
            # conflict is surfaced as a typed domain error (doc 16 §77).
            await self._session.rollback()
            raise DuplicateEmailError() from error

    async def _save(self, account: Account, password_hash: str) -> None:
        await self._session.execute(
            text(
                "INSERT INTO auth.accounts "
                "(account_id, status, primary_email, normalized_email, "
                "email_verified_at, deletion_requested_at, pre_deletion_status, "
                "created_at, updated_at) VALUES "
                "(:account_id, :status, :primary_email, :normalized_email, "
                ":email_verified_at, :deletion_requested_at, :pre_deletion_status, "
                ":created_at, :updated_at)"
            ),
            _params(account),
        )
        await self._session.execute(
            text(
                "INSERT INTO auth.identities "
                "(identity_id, account_id, provider, provider_subject, provider_email) "
                "VALUES (:identity_id, :account_id, 'email', :subject, :email)"
            ),
            {
                "identity_id": uuid4(),
                "account_id": account.account_id,
                "subject": account.normalized_email,
                "email": account.primary_email,
            },
        )
        await self._session.execute(
            text(
                "INSERT INTO auth.password_credentials "
                "(account_id, password_hash, algorithm_version) "
                "VALUES (:account_id, :password_hash, 'argon2id_v1')"
            ),
            {"account_id": account.account_id, "password_hash": password_hash},
        )

    async def find_by_email(self, email: str) -> AccountRecord | None:
        return await self._find(
            "a.normalized_email = :value", {"value": email.strip().casefold()}
        )

    async def find_by_account_id(self, account_id: UUID) -> AccountRecord | None:
        return await self._find("a.account_id = :value", {"value": account_id})

    async def find_by_email_for_account(self, account_id: UUID) -> AccountRecord | None:
        return await self.find_by_account_id(account_id)

    async def update_password_hash(self, account_id: UUID, password_hash: str) -> None:
        await self._session.execute(
            text(
                "UPDATE auth.password_credentials SET password_hash=:password_hash, "
                "password_changed_at=now() WHERE account_id=:account_id"
            ),
            {"account_id": account_id, "password_hash": password_hash},
        )

    async def update(self, account: Account) -> None:
        await self._session.execute(
            text(
                "UPDATE auth.accounts SET status=:status, "
                "email_verified_at=:email_verified_at, "
                "deletion_requested_at=:deletion_requested_at, "
                "pre_deletion_status=:pre_deletion_status, updated_at=:updated_at "
                "WHERE account_id=:account_id"
            ),
            _params(account),
        )

    async def _find(
        self, predicate: str, parameters: dict[str, object]
    ) -> AccountRecord | None:
        result = await self._session.execute(
            text(
                "SELECT a.account_id, a.status, a.primary_email, a.normalized_email, "
                "a.email_verified_at, a.deletion_requested_at, a.pre_deletion_status, "
                "a.created_at, a.updated_at, p.password_hash "
                "FROM auth.accounts a "
                "JOIN auth.password_credentials p ON p.account_id = a.account_id "
                "WHERE " + predicate
            ),
            parameters,
        )
        row = result.mappings().one_or_none()
        if row is None:
            return None
        account = Account(
            account_id=row["account_id"],
            status=AccountStatus(row["status"]),
            primary_email=row["primary_email"],
            normalized_email=row["normalized_email"],
            email_verified_at=row["email_verified_at"],
            deletion_requested_at=row["deletion_requested_at"],
            pre_deletion_status=AccountStatus(row["pre_deletion_status"])
            if row["pre_deletion_status"]
            else None,
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )
        return AccountRecord(account=account, password_hash=row["password_hash"])


def _params(account: Account) -> dict[str, object]:
    return {
        "account_id": account.account_id,
        "status": account.status.value,
        "primary_email": account.primary_email,
        "normalized_email": account.normalized_email,
        "email_verified_at": account.email_verified_at,
        "deletion_requested_at": account.deletion_requested_at,
        "pre_deletion_status": account.pre_deletion_status.value
        if account.pre_deletion_status
        else None,
        "created_at": account.created_at,
        "updated_at": account.updated_at,
    }
