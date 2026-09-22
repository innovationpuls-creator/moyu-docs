from datetime import UTC, datetime
from uuid import uuid4

import pytest
import pytest_asyncio
from app_core.account.application.password_reset import (
    RequestPasswordReset,
    ResetPassword,
)
from app_core.account.application.registration import MailDeliveryError
from app_core.account.domain.account import Account
from app_core.account.domain.token import OneTimeToken, OneTimeTokenType
from app_core.common.exceptions import AuthenticationError, ValidationError
from app_core.session.domain.session import Session
from app_infra.postgres.account_repository import PostgresAccountRepository
from app_infra.postgres.audit_repository import PostgresAuditRepository
from app_infra.postgres.engine import engine
from app_infra.postgres.session_repository import PostgresSessionRepository
from app_infra.postgres.token_repository import PostgresTokenRepository
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


class CapturingMailer:
    def __init__(self, fail=False):
        self.fail, self.secret = fail, None

    async def send_password_reset(self, email, secret):
        if self.fail:
            raise MailDeliveryError("provider unavailable")
        self.secret = secret


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


async def _seed(session):
    account = Account.create_with_email(f"reset-{uuid4()}@example.com")
    accounts, tokens, audit = (
        PostgresAccountRepository(session),
        PostgresTokenRepository(session),
        PostgresAuditRepository(session),
    )
    await accounts.save(account, "old-hash")
    return account, accounts, tokens, audit


async def _token_value(session, token):
    return (
        await session.execute(
            text("SELECT consumed_at FROM auth.one_time_tokens WHERE token_id=:id"),
            {"id": token.token_id},
        )
    ).scalar_one()


@pytest.mark.asyncio
async def test_successful_reset_revokes_sessions_and_audits(db_session):
    account, accounts, tokens, audit = await _seed(db_session)
    now = datetime.now(UTC)
    sessions = PostgresSessionRepository(db_session)
    active = Session.create(account_id=account.account_id, device_id="device", at=now)
    await sessions.create_device_session_atomically(
        account.account_id, "device", active
    )
    token, secret = OneTimeToken.issue(
        account_id=account.account_id,
        token_type=OneTimeTokenType.PASSWORD_RESET,
        at=now,
    )
    await tokens.save(token)
    await ResetPassword(accounts, tokens, sessions, audit, now=lambda: now).execute(
        secret, "A unique passphrase 2026"
    )
    assert (
        await db_session.execute(
            text("SELECT status FROM auth.sessions WHERE session_id=:id"),
            {"id": active.session_id},
        )
    ).scalar_one() == "Revoked"
    assert (
        await db_session.execute(
            text(
                "SELECT COUNT(*) FROM audit.entries WHERE actor_id=:id "
                "AND action='PasswordReset'"
            ),
            {"id": account.account_id},
        )
    ).scalar_one() == 1


@pytest.mark.asyncio
async def test_expired_reset_has_no_database_side_effects(db_session):
    account, accounts, tokens, audit = await _seed(db_session)
    now = datetime.now(UTC)
    token, secret = OneTimeToken.issue(
        account_id=account.account_id,
        token_type=OneTimeTokenType.PASSWORD_RESET,
        at=now,
    )
    token.expires_at = now
    await tokens.save(token)
    before = (
        (await accounts.find_by_account_id(account.account_id)).password_hash,
        await _token_value(db_session, token),
    )
    with pytest.raises(AuthenticationError) as error:
        await ResetPassword(
            accounts,
            tokens,
            PostgresSessionRepository(db_session),
            audit,
            now=lambda: now,
        ).execute(secret, "A unique passphrase 2026")
    assert error.value.error_code == "PASSWORD_RESET_TOKEN_INVALID"
    assert (
        (await accounts.find_by_account_id(account.account_id)).password_hash,
        await _token_value(db_session, token),
    ) == before


@pytest.mark.asyncio
async def test_replayed_reset_has_no_additional_database_side_effects(db_session):
    account, accounts, tokens, audit = await _seed(db_session)
    now = datetime.now(UTC)
    token, secret = OneTimeToken.issue(
        account_id=account.account_id,
        token_type=OneTimeTokenType.PASSWORD_RESET,
        at=now,
    )
    await tokens.save(token)
    reset = ResetPassword(
        accounts, tokens, PostgresSessionRepository(db_session), audit, now=lambda: now
    )
    await reset.execute(secret, "A unique passphrase 2026")
    after = (
        (await accounts.find_by_account_id(account.account_id)).password_hash,
        await _token_value(db_session, token),
    )
    with pytest.raises(AuthenticationError) as error:
        await reset.execute(secret, "Another unique passphrase")
    assert error.value.error_code == "PASSWORD_RESET_TOKEN_INVALID"
    assert (
        (await accounts.find_by_account_id(account.account_id)).password_hash,
        await _token_value(db_session, token),
    ) == after


@pytest.mark.asyncio
async def test_email_verification_token_remains_unconsumed_for_reset(db_session):
    account, accounts, tokens, audit = await _seed(db_session)
    now = datetime.now(UTC)
    token, secret = OneTimeToken.issue(
        account_id=account.account_id,
        token_type=OneTimeTokenType.EMAIL_VERIFICATION,
        at=now,
    )
    await tokens.save(token)
    with pytest.raises(AuthenticationError) as error:
        await ResetPassword(
            accounts,
            tokens,
            PostgresSessionRepository(db_session),
            audit,
            now=lambda: now,
        ).execute(secret, "A unique passphrase 2026")
    assert error.value.error_code == "PASSWORD_RESET_TOKEN_INVALID"
    assert await _token_value(db_session, token) is None


@pytest.mark.asyncio
async def test_password_reset_secret_cannot_verify_email(db_session):
    account, accounts, tokens, audit = await _seed(db_session)
    now = datetime.now(UTC)
    token, secret = OneTimeToken.issue(
        account_id=account.account_id,
        token_type=OneTimeTokenType.PASSWORD_RESET,
        at=now,
    )
    await tokens.save(token)
    consumed = await tokens.consume_by_secret_for_account(
        secret, account.account_id, now
    )
    assert consumed is None
    assert await _token_value(db_session, token) is None


@pytest.mark.asyncio
async def test_invalid_new_password_leaves_reset_token_unconsumed(db_session):
    account, accounts, tokens, audit = await _seed(db_session)
    now = datetime.now(UTC)
    token, secret = OneTimeToken.issue(
        account_id=account.account_id,
        token_type=OneTimeTokenType.PASSWORD_RESET,
        at=now,
    )
    await tokens.save(token)
    with pytest.raises(ValidationError):
        await ResetPassword(
            accounts,
            tokens,
            PostgresSessionRepository(db_session),
            audit,
            now=lambda: now,
        ).execute(secret, "short")
    assert await _token_value(db_session, token) is None


@pytest.mark.asyncio
async def test_new_reset_invalidates_old_and_new_secret_succeeds(db_session):
    account, accounts, tokens, audit = await _seed(db_session)
    old, _ = OneTimeToken.issue(
        account_id=account.account_id,
        token_type=OneTimeTokenType.PASSWORD_RESET,
        at=datetime.now(UTC),
    )
    await tokens.save(old)
    mailer = CapturingMailer()
    await RequestPasswordReset(
        accounts, tokens, audit, mailer, now=lambda: datetime.now(UTC)
    ).execute(account.primary_email)
    assert mailer.secret is not None and await _token_value(db_session, old) is not None
    await ResetPassword(
        accounts,
        tokens,
        PostgresSessionRepository(db_session),
        audit,
        now=lambda: datetime.now(UTC),
    ).execute(mailer.secret, "A unique passphrase 2026")
    assert (
        await accounts.find_by_account_id(account.account_id)
    ).password_hash.startswith("$argon2id$")


@pytest.mark.asyncio
async def test_reset_mail_failure_is_uniform_and_audited_safely(db_session):
    account, accounts, tokens, audit = await _seed(db_session)
    result = await RequestPasswordReset(
        accounts,
        tokens,
        audit,
        CapturingMailer(fail=True),
        now=lambda: datetime.now(UTC),
    ).execute(account.primary_email)
    metadata = (
        await db_session.execute(
            text(
                "SELECT metadata FROM audit.entries WHERE actor_id=:id "
                "AND action='PasswordResetDeliveryFailed'"
            ),
            {"id": account.account_id},
        )
    ).scalar_one()
    assert (
        result.public_message
        and metadata == {"delivery": "failed"}
        and "secret" not in metadata
    )
