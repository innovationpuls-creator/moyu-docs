from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import UUID

import pytest
from app_core.account.application.registration import (
    MailDeliveryError,
    RegisterAccount,
    ResendVerificationEmail,
    VerifyEmail,
)
from app_core.account.domain.account import AccountStatus
from app_core.account.domain.token import OneTimeTokenType
from app_core.common.exceptions import (
    AuthenticationError,
    DuplicateEmailError,
    RateLimitError,
    ValidationError,
)

NOW = datetime(2026, 9, 22, tzinfo=timezone.utc)


class IdempotencyStore:
    def __init__(self) -> None:
        self._values: dict[str, bytes] = {}

    async def get(self, key: str):
        from app_core.account.ports.idempotency_repository import (
            IdempotencyRecord,
            IdempotencyState,
        )

        value = self._values.get(key)
        if value is None:
            return None
        return IdempotencyRecord(
            IdempotencyState.IN_PROGRESS if not value else IdempotencyState.COMPLETED,
            value or None,
        )

    async def claim(self, key: str) -> bool:
        if key in self._values:
            return False
        self._values[key] = b""
        return True

    async def complete(self, key: str, response: bytes) -> None:
        self._values[key] = response


class AccountRepo:
    def __init__(self):
        self.accounts = {}
        self.passwords = {}

    async def save(self, account, password_hash):
        self.accounts[account.normalized_email] = account
        self.passwords[account.account_id] = password_hash

    async def find_by_email(self, email):
        return self._record(self.accounts.get(email.strip().casefold()))

    async def find_by_account_id(self, account_id):
        return self._record(
            next(
                (a for a in self.accounts.values() if a.account_id == account_id), None
            )
        )

    async def find_by_email_for_account(self, account_id):
        return await self.find_by_account_id(account_id)

    async def update(self, account):
        self.accounts[account.normalized_email] = account

    def _record(self, account):
        if account is None:
            return None
        return type(
            "Record",
            (),
            {"account": account, "password_hash": self.passwords[account.account_id]},
        )()


class SessionRepo:
    def __init__(self):
        self.created = []

    async def create_device_session_atomically(
        self, account_id, device_id, new_session
    ):
        self.created.append(new_session)
        return new_session, []


class TokenRepo:
    def __init__(self):
        self.tokens = []

    async def save(self, token):
        self.tokens.append(token)

    async def invalidate_pending(self, account_id, token_type, at):
        for token in self.tokens:
            if token.account_id == account_id and token.token_type is token_type:
                token.consumed_at = at
        return 0

    async def find_by_hash(self, token_hash):
        return next((t for t in self.tokens if t.token_hash == token_hash), None)

    async def consume_by_secret(self, secret, at):
        for token in self.tokens:
            if token.consume(secret, at):
                return token
        return None

    async def consume_by_secret_for_account(self, secret, account_id, at):
        for token in self.tokens:
            if token.account_id == account_id and token.consume(secret, at):
                return token
        return None

    async def count_recent(self, account_id, token_type, since):
        return sum(
            t.account_id == account_id
            and t.token_type is token_type
            and t.created_at >= since
            for t in self.tokens
        )


class AuditRepo:
    def __init__(self):
        self.actions = []

    async def append(self, *, action, **kwargs):
        self.actions.append(action)
        return UUID(int=len(self.actions))


class Mailer:
    def __init__(self, fail=False):
        self.fail, self.messages = fail, []

    async def send_verification(self, email, secret):
        if self.fail:
            raise MailDeliveryError("mail unavailable")
        self.messages.append((email, secret))


class ConflictAccountRepo(AccountRepo):
    async def save(self, account, password_hash):
        raise DuplicateEmailError()


def deps(fail=False):
    return AccountRepo(), SessionRepo(), TokenRepo(), AuditRepo(), Mailer(fail)


@pytest.mark.asyncio
async def test_registration_existing_email_is_uniform_and_never_issues_session():
    accounts, sessions, tokens, audit, mailer = deps()
    use_case = RegisterAccount(
        accounts, sessions, tokens, audit, mailer, now=lambda: NOW
    )
    first = await use_case.execute(
        "victim@example.com", "A unique passphrase 2026", "device-b"
    )
    sessions.created.clear()
    replay = await use_case.execute(
        "VICTIM@example.com", "attacker-passphrase-2026", "device-attacker"
    )
    assert replay.accepted is True
    assert replay.public_message == first.public_message
    assert replay.session is None
    assert sessions.created == []
    assert len(accounts.accounts) == 1
    assert audit.actions == ["AccountCreated"]
    assert mailer.messages == [("victim@example.com", first.verification_secret)]


@pytest.mark.asyncio
async def test_idempotency_replay_of_existing_email_keeps_no_session():
    accounts, sessions, tokens, audit, mailer = deps()
    idem = IdempotencyStore()
    use_case = RegisterAccount(
        accounts, sessions, tokens, audit, mailer, idempotency=idem, now=lambda: NOW
    )
    await use_case.execute("victim@example.com", "A unique passphrase 2026", "device-b")
    first_existing = await use_case.execute(
        "VICTIM@example.com",
        "attacker-passphrase-2026",
        "device-attacker",
        idempotency_key="k",
    )
    replay = await use_case.execute(
        "VICTIM@example.com",
        "attacker-passphrase-2026",
        "device-attacker",
        idempotency_key="k",
    )
    assert first_existing.accepted is True
    assert first_existing.session is None
    assert replay.session is None
    assert replay.public_message == first_existing.public_message
    assert replay.account.account_id == first_existing.account.account_id


@pytest.mark.asyncio
async def test_registration_conflict_maps_to_uniform_existing_email_result():
    accounts, sessions, tokens, audit, mailer = deps()
    baseline = RegisterAccount(
        accounts, sessions, tokens, audit, mailer, now=lambda: NOW
    )
    await baseline.execute("dup@example.com", "A unique passphrase 2026", "device-a")
    existing_message = (
        await baseline.execute(
            "dup@example.com", "A unique passphrase 2026", "device-a"
        )
    ).public_message

    sessions, tokens, audit, mailer = SessionRepo(), TokenRepo(), AuditRepo(), Mailer()
    result = await RegisterAccount(
        ConflictAccountRepo(),
        sessions,
        tokens,
        audit,
        mailer,
        now=lambda: NOW,
    ).execute("DUP@example.com", "A unique passphrase 2026", "device-b")
    assert result.accepted is True
    assert result.session is None
    assert result.public_message == existing_message
    assert sessions.created == []
    assert audit.actions == []
    assert mailer.messages == []

    idem = IdempotencyStore()
    use_case = RegisterAccount(
        ConflictAccountRepo(),
        SessionRepo(),
        TokenRepo(),
        AuditRepo(),
        Mailer(),
        idempotency=idem,
        now=lambda: NOW,
    )
    first_conflict = await use_case.execute(
        "dup@example.com",
        "A unique passphrase 2026",
        "device-b",
        idempotency_key="k-dup",
    )
    replay_conflict = await use_case.execute(
        "dup@example.com",
        "A unique passphrase 2026",
        "device-b",
        idempotency_key="k-dup",
    )
    assert replay_conflict.accepted is True
    assert replay_conflict.session is None
    assert replay_conflict.public_message == first_conflict.public_message


@pytest.mark.asyncio
async def test_registration_core_flow():
    accounts, sessions, tokens, audit, mailer = deps()
    result = await RegisterAccount(
        accounts, sessions, tokens, audit, mailer, now=lambda: NOW
    ).execute(" Alice@Example.com ", "A unique passphrase 2026", "device-a")
    assert result.account.status is AccountStatus.PENDING_VERIFICATION
    assert result.session.account_id == result.account.account_id
    assert (
        result.verification_secret
        and tokens.tokens[0].token_type is OneTimeTokenType.EMAIL_VERIFICATION
    )
    assert audit.actions == ["AccountCreated"]


@pytest.mark.asyncio
async def test_registration_mail_failure_does_not_rollback():
    accounts, sessions, tokens, audit, mailer = deps(True)
    result = await RegisterAccount(
        accounts, sessions, tokens, audit, mailer, now=lambda: NOW
    ).execute("a@example.com", "A unique passphrase 2026", "device-a")
    assert (
        result.mail_delivery_failed
        and accounts.accounts["a@example.com"].status
        is AccountStatus.PENDING_VERIFICATION
    )


@pytest.mark.asyncio
async def test_idempotency_duplicate_password_and_verification_ownership():
    accounts, sessions, tokens, audit, mailer = deps()
    idem = IdempotencyStore()
    use_case = RegisterAccount(
        accounts, sessions, tokens, audit, mailer, idempotency=idem, now=lambda: NOW
    )
    first = await use_case.execute(
        "one@example.com", "A unique passphrase 2026", "device-a", idempotency_key="k"
    )
    replay = await use_case.execute(
        "one@example.com",
        "A unique passphrase 2026",
        "device-a",
        idempotency_key="k",
    )
    assert replay.account.account_id == first.account.account_id
    assert replay.session.session_id == first.session.session_id
    assert replay.public_message == first.public_message
    assert replay.verification_secret is None
    with pytest.raises(ValidationError):
        await use_case.execute("ONE@example.com", "short", "device-b")
    second = await use_case.execute(
        "two@example.com", "A unique passphrase 2026", "device-b"
    )
    with pytest.raises(AuthenticationError) as error:
        await VerifyEmail(accounts, tokens, audit, now=lambda: NOW).execute(
            first.verification_secret, second.account.account_id
        )
    assert error.value.error_code == "EMAIL_VERIFICATION_TOKEN_INVALID"
    assert tokens.tokens[0].consumed_at is None


@pytest.mark.parametrize(
    "terminal_status",
    [AccountStatus.DISABLED, AccountStatus.DELETION_PENDING, AccountStatus.DELETED],
)
@pytest.mark.asyncio
async def test_verify_email_does_not_consume_token_for_unverifiable_account(
    terminal_status: AccountStatus,
):
    accounts, sessions, tokens, audit, mailer = deps()
    registration = await RegisterAccount(
        accounts, sessions, tokens, audit, mailer, now=lambda: NOW
    ).execute("a@example.com", "A unique passphrase 2026", "device-a")
    accounts.accounts["a@example.com"].status = terminal_status
    with pytest.raises(AuthenticationError) as error:
        await VerifyEmail(accounts, tokens, audit, now=lambda: NOW).execute(
            registration.verification_secret, registration.account.account_id
        )
    assert error.value.error_code == "EMAIL_VERIFICATION_TOKEN_INVALID"
    token = tokens.tokens[0]
    assert token.consumed_at is None
    assert await tokens.find_by_hash(token.token_hash) is token
    assert accounts.accounts["a@example.com"].status is terminal_status


@pytest.mark.asyncio
async def test_verify_and_resend_rate_limit():
    accounts, sessions, tokens, audit, mailer = deps()
    registration = await RegisterAccount(
        accounts, sessions, tokens, audit, mailer, now=lambda: NOW
    ).execute("a@example.com", "A unique passphrase 2026", "device-a")
    await VerifyEmail(accounts, tokens, audit, now=lambda: NOW).execute(
        registration.verification_secret, registration.account.account_id
    )
    assert registration.account.status is AccountStatus.ACTIVE
    registration = await RegisterAccount(
        accounts, sessions, tokens, audit, mailer, now=lambda: NOW
    ).execute("b@example.com", "A unique passphrase 2026", "device-a")
    with pytest.raises(RateLimitError) as error:
        await ResendVerificationEmail(
            accounts, tokens, mailer, now=lambda: NOW
        ).execute(registration.account.account_id)
    assert error.value.error_code == "RATE_LIMITED"


@pytest.mark.asyncio
async def test_resend_mail_failure_is_audited_and_token_not_saved():
    accounts, sessions, tokens, audit, mailer = deps(True)
    registration = await RegisterAccount(
        accounts, sessions, tokens, audit, Mailer(), now=lambda: NOW
    ).execute("a@example.com", "A unique passphrase 2026", "device-a")
    tokens.tokens.clear()
    with pytest.raises(MailDeliveryError):
        await ResendVerificationEmail(
            accounts,
            tokens,
            mailer,
            audit=audit,
            now=lambda: NOW + timedelta(seconds=61),
        ).execute(registration.account.account_id)
    assert (
        tokens.tokens == [] and audit.actions[-1] == "VerificationEmailDeliveryFailed"
    )
