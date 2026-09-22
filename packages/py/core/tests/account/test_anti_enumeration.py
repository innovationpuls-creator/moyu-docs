from __future__ import annotations

import time
from datetime import datetime, timezone

import pytest
from app_core.account.application.password_reset import RequestPasswordReset
from app_core.account.application.registration import RegisterAccount
from app_core.account.domain.account import Account
from app_core.account.domain.password_policy import PasswordHasher
from app_core.account.domain.timing_shield import (
    UNIFORM_AUTH_MESSAGES,
    TimingShield,
)
from app_core.common.exceptions import AuthenticationError
from app_core.session.application.authentication import (
    LoginWithPassword,
    PasswordVerifier,
)

NOW = datetime(2026, 9, 22, tzinfo=timezone.utc)


class RecordingShield:
    """Records perform_dummy_hash invocations in place of TimingShield."""

    def __init__(self) -> None:
        self.invocations = 0

    def perform_dummy_hash(self) -> None:
        self.invocations += 1


class AccountRepo:
    def __init__(self) -> None:
        self.accounts: dict[str, Account] = {}

    async def save(self, account: Account, password_hash: str) -> None:
        self.accounts[account.normalized_email] = account

    async def find_by_email(self, email: str):
        account = self.accounts.get(email.strip().casefold())
        if account is None:
            return None
        return type("R", (), {"account": account})()


class SessionRepo:
    def __init__(self) -> None:
        self.created: list[object] = []

    async def create_device_session_atomically(
        self, account_id, device_id, new_session
    ):
        self.created.append(new_session)
        return new_session, []


class TokenRepo:
    def __init__(self) -> None:
        self.saved: list[object] = []

    async def save(self, token) -> None:
        self.saved.append(token)


class AuditRepo:
    def __init__(self) -> None:
        self.actions: list[str] = []

    async def append(self, *, action: str, **kwargs) -> None:
        self.actions.append(action)


class Mailer:
    def __init__(self) -> None:
        self.messages: list[tuple[str, str]] = []

    async def send_verification(self, email: str, secret: str) -> None:
        self.messages.append((email, secret))

    async def send_password_reset(self, email: str, secret: str) -> None:
        self.messages.append((email, secret))


class ResetAccounts:
    def __init__(self, account: Account | None = None) -> None:
        self.account = account

    async def find_by_email(self, email: str):
        return (
            None if self.account is None else type("R", (), {"account": self.account})()
        )


class ResetTokens:
    async def invalidate_pending(self, account_id, token_type, at) -> None:
        pass

    async def save(self, token) -> None:
        pass


class RecordingVerifier(PasswordVerifier):
    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    def verify(self, password: str, password_hash: str) -> bool:
        self.calls.append((password, password_hash))
        return False


def test_timing_shield_computes_constant_work() -> None:
    start = time.perf_counter()
    TimingShield.perform_dummy_hash()
    duration = time.perf_counter() - start
    assert duration > 0.05  # Argon2id execution floor


def test_uniform_messages_defined() -> None:
    assert "如果该邮箱可以继续注册" in UNIFORM_AUTH_MESSAGES["REGISTER_SUCCESS"]
    assert "如果该邮箱已注册" in UNIFORM_AUTH_MESSAGES["FORGOT_PASSWORD_SUCCESS"]
    assert "邮箱或密码错误" in UNIFORM_AUTH_MESSAGES["INVALID_CREDENTIALS"]


def test_precomputed_dummy_hash_is_a_real_argon2id_hash() -> None:
    assert PasswordHasher.verify(
        TimingShield.DUMMY_PASSWORD, TimingShield.DUMMY_PASSWORD_HASH
    )


@pytest.mark.asyncio
async def test_registration_existing_email_invokes_timing_shield() -> None:
    accounts, sessions, tokens, audit, mailer = (
        AccountRepo(),
        SessionRepo(),
        TokenRepo(),
        AuditRepo(),
        Mailer(),
    )
    seed = RegisterAccount(accounts, sessions, tokens, audit, mailer, now=lambda: NOW)
    await seed.execute("existing@example.com", "A unique passphrase 2026", "device-a")

    shield = RecordingShield()
    result = await RegisterAccount(
        accounts, sessions, tokens, audit, mailer, shield=shield, now=lambda: NOW
    ).execute("EXISTING@example.com", "attacker-passphrase-2026", "device-b")

    assert result.session is None
    assert shield.invocations == 1
    assert result.public_message == UNIFORM_AUTH_MESSAGES["REGISTER_SUCCESS_EN"]


@pytest.mark.asyncio
async def test_registration_new_email_does_not_run_dummy_hash() -> None:
    accounts, sessions, tokens, audit, mailer = (
        AccountRepo(),
        SessionRepo(),
        TokenRepo(),
        AuditRepo(),
        Mailer(),
    )
    shield = RecordingShield()
    await RegisterAccount(
        accounts, sessions, tokens, audit, mailer, shield=shield, now=lambda: NOW
    ).execute("brand-new@example.com", "A unique passphrase 2026", "device-a")

    assert shield.invocations == 0
    assert sessions.created != []


@pytest.mark.asyncio
async def test_forgot_password_missing_email_invokes_timing_shield() -> None:
    shield = RecordingShield()
    result = await RequestPasswordReset(
        ResetAccounts(),
        ResetTokens(),
        AuditRepo(),
        Mailer(),
        shield=shield,
        now=lambda: NOW,
    ).execute("missing@example.com")

    assert shield.invocations == 1
    assert result.public_message == UNIFORM_AUTH_MESSAGES["FORGOT_PASSWORD_SUCCESS_EN"]


@pytest.mark.asyncio
async def test_forgot_password_existing_email_does_not_run_dummy_hash() -> None:
    shield = RecordingShield()
    result = await RequestPasswordReset(
        ResetAccounts(Account.create_with_email("a@example.com", at=NOW)),
        ResetTokens(),
        AuditRepo(),
        Mailer(),
        shield=shield,
        now=lambda: NOW,
    ).execute("a@example.com")

    assert shield.invocations == 0
    assert result.public_message == UNIFORM_AUTH_MESSAGES["FORGOT_PASSWORD_SUCCESS_EN"]


@pytest.mark.asyncio
async def test_login_unknown_email_verifies_against_centralized_dummy_hash() -> None:
    verifier = RecordingVerifier()
    accounts = AccountRepo()

    with pytest.raises(AuthenticationError) as error:
        await LoginWithPassword(
            accounts, SessionRepo(), verifier=verifier, now=lambda: NOW
        ).execute("missing@example.com", "attacker-passphrase-2026", "device-a")

    assert error.value.error_code == "INVALID_CREDENTIALS"
    assert error.value.message == UNIFORM_AUTH_MESSAGES["INVALID_CREDENTIALS_EN"]
    assert verifier.calls == [
        ("attacker-passphrase-2026", TimingShield.DUMMY_PASSWORD_HASH)
    ]
