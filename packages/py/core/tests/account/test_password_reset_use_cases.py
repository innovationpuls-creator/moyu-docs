from datetime import UTC, datetime

import pytest
from app_core.account.application.password_reset import (
    RequestPasswordReset,
    ResetPassword,
)
from app_core.account.domain.account import Account
from app_core.account.domain.token import OneTimeToken, OneTimeTokenType
from app_core.common.exceptions import AuthenticationError


class Accounts:
    def __init__(self, account=None):
        self.account, self.password_hash = account, "old"

    async def find_by_email(self, email):
        return (
            None if self.account is None else type("R", (), {"account": self.account})()
        )

    async def update_password_hash(self, account_id, password_hash):
        self.password_hash = password_hash


class Tokens:
    def __init__(self):
        self.tokens = []

    async def invalidate_pending(self, account_id, token_type, at):
        for token in self.tokens:
            token.consumed_at = at

    async def save(self, token):
        self.tokens.append(token)

    async def consume_password_reset_by_secret(self, secret, at):
        for token in self.tokens:
            if token.token_type is OneTimeTokenType.PASSWORD_RESET and token.consume(
                secret, at
            ):
                return token
        return None


class Sessions:
    def __init__(self):
        self.revoked = []

    async def revoke_all_sessions(self, account_id, reason):
        self.revoked.append((account_id, reason))
        return []


class Audit:
    def __init__(self):
        self.actions = []

    async def append(self, *, action, **kwargs):
        self.actions.append(action)


class Mailer:
    def __init__(self):
        self.messages = []

    async def send_password_reset(self, email, secret):
        self.messages.append((email, secret))


@pytest.mark.asyncio
async def test_request_reset_is_uniform_and_only_issues_for_existing_account():
    now = datetime.now(UTC)
    account, tokens, audit, mailer = (
        Account.create_with_email("a@example.com"),
        Tokens(),
        Audit(),
        Mailer(),
    )
    existing = await RequestPasswordReset(
        Accounts(account), tokens, audit, mailer, now=lambda: now
    ).execute("a@example.com")
    missing = await RequestPasswordReset(
        Accounts(), Tokens(), Audit(), Mailer(), now=lambda: now
    ).execute("missing@example.com")
    assert existing.public_message == missing.public_message
    assert len(tokens.tokens) == 1 and mailer.messages


@pytest.mark.asyncio
async def test_reset_consumes_token_updates_password_and_revokes_sessions():
    now = datetime.now(UTC)
    account, tokens, sessions, audit = (
        Account.create_with_email("a@example.com"),
        Tokens(),
        Sessions(),
        Audit(),
    )
    token, secret = OneTimeToken.issue(
        account_id=account.account_id,
        token_type=OneTimeTokenType.PASSWORD_RESET,
        at=now,
    )
    tokens.tokens.append(token)
    accounts = Accounts(account)
    await ResetPassword(accounts, tokens, sessions, audit, now=lambda: now).execute(
        secret, "A unique passphrase 2026"
    )
    assert accounts.password_hash.startswith("$argon2id$")
    assert sessions.revoked == [(account.account_id, "PasswordReset")]
    assert audit.actions == ["PasswordReset"]
    with pytest.raises(AuthenticationError) as error:
        await ResetPassword(accounts, tokens, sessions, audit, now=lambda: now).execute(
            secret, "Another unique passphrase"
        )
    assert error.value.error_code == "PASSWORD_RESET_TOKEN_INVALID"
