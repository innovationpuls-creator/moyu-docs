from __future__ import annotations

from datetime import datetime, timezone

import pytest
from app_core.account.domain.account import Account, AccountStatus
from app_core.account.domain.password_policy import PasswordHasher
from app_core.account.ports.account_repository import AccountRecord
from app_core.common.exceptions import AuthenticationError
from app_core.session.application.authentication import (
    LoginWithPassword,
    Logout,
    PasswordVerifier,
    Reauthenticate,
)
from app_core.session.domain.session import Session, SessionStatus

NOW = datetime(2026, 9, 22, tzinfo=timezone.utc)


class AccountRepository:
    def __init__(self, account: Account | None, password: str) -> None:
        self.account = account
        self.password_hash = PasswordHasher.hash(password)
        self.lookups: list[str] = []

    async def find_by_email(self, email: str) -> AccountRecord | None:
        self.lookups.append(email)
        if self.account is None:
            return None
        return AccountRecord(self.account, self.password_hash)

    async def find_by_account_id(self, account_id) -> AccountRecord | None:
        if self.account is None or self.account.account_id != account_id:
            return None
        return AccountRecord(self.account, self.password_hash)


class RecordingVerifier(PasswordVerifier):
    def __init__(self, result: bool) -> None:
        self.result = result
        self.calls: list[tuple[str, str]] = []

    def verify(self, password: str, password_hash: str) -> bool:
        self.calls.append((password, password_hash))
        return self.result


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


class SessionRepository:
    def __init__(self) -> None:
        self.created: list[Session] = []
        self.logged_out: list[object] = []
        self.sessions: dict[object, Session] = {}
        self.reauthenticated: list[Session] = []

    async def create_device_session_atomically(
        self, account_id, device_id, new_session
    ) -> tuple[Session, list[Session]]:
        self.created.append(new_session)
        self.sessions[new_session.session_id] = new_session
        return new_session, []

    async def find_by_id(self, session_id):
        return self.sessions.get(session_id)

    async def mark_logged_out(self, session_id) -> None:
        self.logged_out.append(session_id)
        session = self.sessions.get(session_id)
        if session is not None:
            session.logout(NOW)

    async def update_last_strong_auth(self, session: Session) -> None:
        self.reauthenticated.append(session)


def active_account() -> Account:
    account = Account.create_with_email("Alice@Example.com", at=NOW)
    account.verify_email(at=NOW)
    return account


@pytest.mark.asyncio
async def test_login_normalizes_email_and_creates_fresh_session() -> None:
    account = active_account()
    accounts = AccountRepository(account, "A unique passphrase 2026")
    sessions = SessionRepository()

    result = await LoginWithPassword(accounts, sessions, now=lambda: NOW).execute(
        "  ALICE@example.com ", "A unique passphrase 2026", "device-a"
    )

    assert accounts.lookups == ["alice@example.com"]
    assert result.account is account
    assert result.session is sessions.created[0]
    assert result.session.session_id != account.account_id
    assert result.replaced_sessions == []


@pytest.mark.asyncio
async def test_login_idempotency_same_key_replays_same_session() -> None:
    account = active_account()
    accounts = AccountRepository(account, "A unique passphrase 2026")
    sessions = SessionRepository()
    login = LoginWithPassword(
        accounts, sessions, idempotency=IdempotencyStore(), now=lambda: NOW
    )

    first = await login.execute(
        "alice@example.com",
        "A unique passphrase 2026",
        "device-a",
        idempotency_key="login-k",
    )
    replay = await login.execute(
        "alice@example.com",
        "A unique passphrase 2026",
        "device-a",
        idempotency_key="login-k",
    )

    assert replay.session.session_id == first.session.session_id
    assert replay.account.account_id == first.account.account_id
    assert replay.recovery_mode == first.recovery_mode
    assert len(sessions.created) == 1


@pytest.mark.asyncio
async def test_login_idempotency_distinct_keys_create_separate_sessions() -> None:
    account = active_account()
    accounts = AccountRepository(account, "A unique passphrase 2026")
    sessions = SessionRepository()
    store = IdempotencyStore()
    login = LoginWithPassword(accounts, sessions, idempotency=store, now=lambda: NOW)

    first = await login.execute(
        "alice@example.com",
        "A unique passphrase 2026",
        "device-a",
        idempotency_key="k1",
    )
    second = await login.execute(
        "alice@example.com",
        "A unique passphrase 2026",
        "device-b",
        idempotency_key="k2",
    )

    assert second.session.session_id != first.session.session_id
    assert len(sessions.created) == 2


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "account_exists, password", [(False, "wrong"), (True, "wrong")]
)
async def test_login_uses_same_authentication_error_for_absent_or_wrong_password(
    account_exists: bool, password: str
) -> None:
    account = active_account() if account_exists else None
    accounts = AccountRepository(account, "A unique passphrase 2026")

    with pytest.raises(AuthenticationError) as error:
        await LoginWithPassword(accounts, SessionRepository(), now=lambda: NOW).execute(
            "alice@example.com", password, "device-a"
        )

    assert error.value.error_code == "INVALID_CREDENTIALS"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "status", [None, AccountStatus.DISABLED, AccountStatus.DELETED]
)
async def test_login_failure_paths_always_run_one_password_verification(
    status: AccountStatus | None,
) -> None:
    account = active_account() if status is not None else None
    if account is not None:
        if status is AccountStatus.DISABLED:
            account.disable(at=NOW)
        else:
            account.purge(at=NOW)
    verifier = RecordingVerifier(result=False)

    with pytest.raises(AuthenticationError):
        await LoginWithPassword(
            AccountRepository(account, "A unique passphrase 2026"),
            SessionRepository(),
            verifier=verifier,
            now=lambda: NOW,
        ).execute("alice@example.com", "wrong", "device-a")

    assert len(verifier.calls) == 1


@pytest.mark.asyncio
async def test_login_rejects_disabled_and_deleted_accounts() -> None:
    for action in ("disable", "purge"):
        account = active_account()
        getattr(account, action)(at=NOW)
        with pytest.raises(AuthenticationError) as error:
            await LoginWithPassword(
                AccountRepository(account, "A unique passphrase 2026"),
                SessionRepository(),
                now=lambda: NOW,
            ).execute("alice@example.com", "A unique passphrase 2026", "device-a")
        assert error.value.error_code == "INVALID_CREDENTIALS"


@pytest.mark.asyncio
async def test_login_allows_pending_and_deletion_pending_accounts() -> None:
    for status in (AccountStatus.PENDING_VERIFICATION, AccountStatus.DELETION_PENDING):
        account = Account.create_with_email("alice@example.com", at=NOW)
        if status is AccountStatus.DELETION_PENDING:
            account.request_deletion(at=NOW)
        result = await LoginWithPassword(
            AccountRepository(account, "A unique passphrase 2026"),
            SessionRepository(),
            now=lambda: NOW,
        ).execute("alice@example.com", "A unique passphrase 2026", "device-a")
        assert result.account.status is status
        assert result.recovery_mode is (status is AccountStatus.DELETION_PENDING)


@pytest.mark.asyncio
async def test_logout_only_marks_requested_session_logged_out_idempotently() -> None:
    sessions = SessionRepository()
    current = Session.create(
        account_id=active_account().account_id, device_id="a", at=NOW
    )
    other = Session.create(
        account_id=active_account().account_id, device_id="b", at=NOW
    )
    sessions.sessions[current.session_id] = current
    sessions.sessions[other.session_id] = other
    logout = Logout(sessions)

    await logout.execute(current.session_id)
    await logout.execute(current.session_id)

    assert current.status is SessionStatus.LOGGED_OUT
    assert other.status is SessionStatus.ACTIVE


@pytest.mark.asyncio
async def test_reauthentication_persists_recent_auth_time_after_verification() -> None:
    account = active_account()
    session = Session.create(
        account_id=account.account_id, device_id="device-a", at=NOW
    )
    accounts = AccountRepository(account, "A unique passphrase 2026")
    sessions = SessionRepository()
    sessions.sessions[session.session_id] = session

    result = await Reauthenticate(accounts, sessions, now=lambda: NOW).execute(
        session.session_id, "A unique passphrase 2026"
    )

    assert result is session
    assert session.last_strong_auth_at == NOW
    assert sessions.reauthenticated == [session]
