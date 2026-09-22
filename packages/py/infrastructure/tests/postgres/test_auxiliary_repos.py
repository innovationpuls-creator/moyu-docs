from datetime import UTC, datetime
from uuid import uuid4

import pytest
import pytest_asyncio
from app_core.account.application.registration import MailDeliveryError
from app_core.account.ports.idempotency_repository import IdempotencyState
from app_core.common.exceptions import ValidationError
from app_infra.postgres.engine import engine
from app_infra.postgres.idempotency_repository import PostgresIdempotencyRepository
from app_infra.postgres.registration_composition import build_registration_use_case
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


class FailingMailer:
    async def send_verification(self, email: str, secret: str) -> None:
        raise MailDeliveryError("provider unavailable")


class RecordingMailer:
    def __init__(self) -> None:
        self.messages: list[tuple[str, str]] = []

    async def send_verification(self, email: str, secret: str) -> None:
        self.messages.append((email, secret))


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
async def test_two_postgres_sessions_contend_then_replay() -> None:
    key = f"concurrent-{uuid4()}"
    async with (
        engine.connect() as first_connection,
        engine.connect() as second_connection,
    ):
        first = AsyncSession(first_connection, expire_on_commit=False)
        second = AsyncSession(second_connection, expire_on_commit=False)
        try:
            first_repository = PostgresIdempotencyRepository(first)
            second_repository = PostgresIdempotencyRepository(second)
            assert await first_repository.claim(key)
            await first.commit()
            assert await second_repository.claim(key) is False
            in_progress = await second_repository.get(key)
            assert in_progress is not None
            assert in_progress.state is IdempotencyState.IN_PROGRESS
            await first_repository.complete(key, b'{"account_id":"replay"}')
            await first.commit()
            replay = await second_repository.get(key)
            assert replay is not None
            assert replay.state is IdempotencyState.COMPLETED
            assert replay.response == b'{"account_id":"replay"}'
        finally:
            await first.close()
            await second.close()


@pytest.mark.asyncio
async def test_failed_registration_does_not_poison_idempotency_key() -> None:
    email = f"poison-{uuid4()}@example.com"
    key = f"poison-{uuid4()}"
    async with (
        engine.connect() as first_connection,
        engine.connect() as second_connection,
    ):
        first = AsyncSession(first_connection, expire_on_commit=False)
        second = AsyncSession(second_connection, expire_on_commit=False)
        try:
            first_use_case = build_registration_use_case(
                first, RecordingMailer(), now=lambda: datetime.now(UTC)
            )
            with pytest.raises(ValidationError):
                await first_use_case.execute(
                    email, "short", "device-a", idempotency_key=key
                )
            await first.rollback()
            await first.close()

            second_use_case = build_registration_use_case(
                second, RecordingMailer(), now=lambda: datetime.now(UTC)
            )
            result = await second_use_case.execute(
                email, "A unique passphrase 2026", "device-a", idempotency_key=key
            )
            assert result.session is not None
            record = await PostgresIdempotencyRepository(second).get(key)
            assert record is not None
            assert record.state is IdempotencyState.COMPLETED
            account_count = await second.scalar(
                text(
                    "SELECT count(*) FROM auth.accounts WHERE normalized_email = :email"
                ),
                {"email": email.casefold()},
            )
            assert account_count == 1
        finally:
            await second.close()


@pytest.mark.asyncio
async def test_registration_mail_failure_writes_safe_audit_metadata(
    db_session: AsyncSession,
) -> None:
    use_case = build_registration_use_case(
        db_session, FailingMailer(), now=lambda: datetime.now(UTC)
    )
    result = await use_case.execute(
        f"mail-{uuid4()}@example.com", "A unique passphrase 2026", "audit-device"
    )
    row = (
        await db_session.execute(
            text(
                "SELECT metadata FROM audit.entries WHERE actor_id=:account_id "
                "AND action='VerificationEmailDeliveryFailed'"
            ),
            {"account_id": result.account.account_id},
        )
    ).one()
    assert row.metadata == {"delivery": "failed"}
    assert "secret" not in row.metadata
