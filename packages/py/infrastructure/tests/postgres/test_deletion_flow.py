from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
import pytest_asyncio
from app_core.account.application.deletion import (
    CancelAccountDeletion,
    ProcessAccountPurge,
    RequestAccountDeletion,
)
from app_core.account.domain.account import Account
from app_core.common.exceptions import ConflictError
from app_core.session.domain.session import (
    Session,
    SessionInvalidationReason,
    SessionStatus,
)
from app_infra.postgres.account_repository import PostgresAccountRepository
from app_infra.postgres.deletion_repository import PostgresDeletionRepository
from app_infra.postgres.engine import engine
from app_infra.postgres.session_repository import PostgresSessionRepository
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


class NoOwner:
    async def has_sole_workspace_ownership(self, account_id):
        return False, None


class SoleOwner:
    async def has_sole_workspace_ownership(self, account_id):
        return True, f"workspace-{account_id}"


class Audit:
    async def append(self, **kwargs):
        return None


@pytest_asyncio.fixture
async def db_session() -> AsyncSession:
    async with engine.connect() as connection:
        transaction = await connection.begin()
        factory = async_sessionmaker(
            bind=connection,
            expire_on_commit=False,
            class_=AsyncSession,
            join_transaction_mode="create_savepoint",
        )
        async with factory() as session:
            yield session
            await session.rollback()
        await transaction.rollback()


async def _setup(session):
    now = datetime.now(UTC)
    account = Account.create_with_email(f"delete-{uuid4()}@example.com", at=now)
    account.verify_email(now)
    accounts = PostgresAccountRepository(session)
    await accounts.save(account, "hash")
    sessions = PostgresSessionRepository(session)
    current = Session.create(account_id=account.account_id, device_id="d", at=now)
    current.reauthenticate(now)
    await sessions.create_device_session_atomically(account.account_id, "d", current)
    return now, account, accounts, sessions, current


@pytest.mark.asyncio
async def test_postgres_deletion_request_persists_and_is_idempotent(
    db_session: AsyncSession,
):
    now, account, accounts, sessions, current = await _setup(db_session)
    deletion = PostgresDeletionRepository(db_session)
    use_case = RequestAccountDeletion(
        accounts, sessions, NoOwner(), Audit(), deletion, now=lambda: now
    )
    await use_case.execute(account.account_id, current.session_id)
    await use_case.execute(account.account_id, current.session_id)
    row = (
        await db_session.execute(
            text(
                "SELECT state, execute_after FROM auth.account_deletion_requests "
                "WHERE account_id=:id"
            ),
            {"id": account.account_id},
        )
    ).one()
    assert row.state == "Pending" and row.execute_after == now + timedelta(days=30)


@pytest.mark.asyncio
async def test_postgres_deletion_sole_owner_does_not_create_request(
    db_session: AsyncSession,
):
    now, account, accounts, sessions, current = await _setup(db_session)
    with pytest.raises(ConflictError) as error:
        await RequestAccountDeletion(
            accounts,
            sessions,
            SoleOwner(),
            Audit(),
            PostgresDeletionRepository(db_session),
            now=lambda: now,
        ).execute(account.account_id, current.session_id)
    assert error.value.error_code == "ACCOUNT_DELETION_SOLE_OWNER"
    assert "workspace-" in error.value.message
    assert (
        await db_session.execute(
            text(
                "SELECT COUNT(*) FROM auth.account_deletion_requests "
                "WHERE account_id=:id"
            ),
            {"id": account.account_id},
        )
    ).scalar_one() == 0


@pytest.mark.asyncio
async def test_postgres_cancel_marks_request_cancelled_and_restores_account(
    db_session: AsyncSession,
):
    now, account, accounts, sessions, current = await _setup(db_session)
    deletion = PostgresDeletionRepository(db_session)
    await RequestAccountDeletion(
        accounts, sessions, NoOwner(), Audit(), deletion, now=lambda: now
    ).execute(account.account_id, current.session_id)
    await CancelAccountDeletion(accounts, Audit(), deletion, now=lambda: now).execute(
        account.account_id
    )
    row = (
        await db_session.execute(
            text(
                "SELECT state, cancelled_at "
                "FROM auth.account_deletion_requests "
                "WHERE account_id=:id"
            ),
            {"id": account.account_id},
        )
    ).one()
    assert row.state == "Cancelled" and row.cancelled_at is not None
    assert (
        await accounts.find_by_account_id(account.account_id)
    ).account.status.value == "Active"


@pytest.mark.asyncio
async def test_postgres_purge_after_grace_marks_deleted_and_revokes_session(
    db_session: AsyncSession,
):
    now, account, accounts, sessions, current = await _setup(db_session)
    account.request_deletion(now - timedelta(days=30))
    await accounts.update(account)
    deletion = PostgresDeletionRepository(db_session)
    await deletion.schedule(account.account_id, now - timedelta(days=1))
    await ProcessAccountPurge(
        accounts, sessions, Audit(), deletion, now=lambda: now
    ).execute(account.account_id)
    assert (
        await accounts.find_by_account_id(account.account_id)
    ).account.status.value == "Deleted"
    status = (
        await db_session.execute(
            text(
                "SELECT status, invalidation_reason FROM auth.sessions "
                "WHERE session_id=:id"
            ),
            {"id": current.session_id},
        )
    ).one()
    assert status == ("Revoked", "AccountDeleted")
    hydrated = await sessions.find_by_id(current.session_id)
    assert hydrated is not None
    assert hydrated.status is SessionStatus.REVOKED
    assert hydrated.invalidation_reason is SessionInvalidationReason.ACCOUNT_DELETED
    deletion_row = (
        await db_session.execute(
            text(
                "SELECT state FROM auth.account_deletion_requests WHERE account_id=:id"
            ),
            {"id": account.account_id},
        )
    ).one()
    assert deletion_row.state == "Completed"
