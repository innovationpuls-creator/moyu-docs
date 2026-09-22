from __future__ import annotations

from uuid import uuid4

import pytest
import pytest_asyncio
from app_core.account.domain.account import Account
from app_core.common.exceptions import DuplicateEmailError
from app_infra.postgres.account_repository import PostgresAccountRepository
from app_infra.postgres.engine import engine
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


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


@pytest.mark.asyncio
async def test_account_repository_finds_by_id_and_updates_lifecycle(
    db_session: AsyncSession,
) -> None:
    repository = PostgresAccountRepository(db_session)
    account = Account.create_with_email("update@example.com")
    await repository.save(account, "hash")
    found = await repository.find_by_account_id(account.account_id)
    assert found is not None
    found.account.verify_email()
    await repository.update(found.account)
    updated = await repository.find_by_email_for_account(account.account_id)
    assert updated is not None
    assert updated.account.status.value == "Active"


@pytest.mark.asyncio
async def test_account_repository_save_conflict_raises_duplicate_email_error() -> None:
    email = f"dup-save-{uuid4()}@example.com"
    async with (
        engine.connect() as first_connection,
        engine.connect() as second_connection,
    ):
        first = AsyncSession(first_connection, expire_on_commit=False)
        second = AsyncSession(second_connection, expire_on_commit=False)
        try:
            first_repository = PostgresAccountRepository(first)
            first_account = Account.create_with_email(email)
            await first_repository.save(first_account, "hash")
            await first.commit()

            second_repository = PostgresAccountRepository(second)
            conflicting = Account.create_with_email(email.casefold().upper())
            with pytest.raises(DuplicateEmailError) as error:
                await second_repository.save(conflicting, "other-hash")
            assert error.value.category == "Conflict"
            assert error.value.error_code == "EMAIL_ALREADY_EXISTS"
            await second.rollback()

            count = await second.scalar(
                text(
                    "SELECT count(*) FROM auth.accounts WHERE normalized_email = :email"
                ),
                {"email": email.casefold()},
            )
            assert count == 1
        finally:
            await first.close()
            await second.close()
