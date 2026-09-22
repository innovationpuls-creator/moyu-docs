from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from app_core.account.application.deletion import (
    CancelAccountDeletion,
    ProcessAccountPurge,
    RequestAccountDeletion,
)
from app_core.account.domain.account import Account, AccountStatus
from app_core.common.exceptions import (
    AuthenticationError,
    ConflictError,
    NotFoundError,
    ValidationError,
)
from app_core.session.domain.session import Session
from fakes.fake_workspace_ownership import FakeWorkspaceOwnershipQueryAdapter


class Accounts:
    def __init__(self, account):
        self.account = account

    async def find_by_account_id(self, account_id):
        if self.account is None:
            return None
        return type("R", (), {"account": self.account})()

    async def update(self, account):
        self.account = account


class Sessions:
    def __init__(self, session):
        self.session, self.revoked = session, []

    async def find_by_id(self, session_id):
        return self.session

    async def revoke_all_sessions(self, account_id, reason):
        self.revoked.append((account_id, reason))
        return []


class Audit:
    def __init__(self):
        self.actions = []

    async def append(self, *, action, **kwargs):
        self.actions.append(action)


class Deletion:
    def __init__(self):
        self.completed = []

    async def complete(self, account_id, at):
        self.completed.append((account_id, at))
        return True


class Schedule:
    def __init__(self):
        self.scheduled = []

    async def schedule(self, account_id, execute_after):
        self.scheduled.append((account_id, execute_after))

    async def cancel(self, account_id, at):
        return True


@pytest.mark.asyncio
async def test_request_and_cancel_deletion_preserves_pre_state():
    now = datetime.now(UTC)
    account = Account.create_with_email("a@example.com", at=now)
    account.verify_email(now)
    session = Session.create(account_id=account.account_id, device_id="d", at=now)
    session.reauthenticate(now)
    schedule = Schedule()
    audit = Audit()
    await RequestAccountDeletion(
        Accounts(account),
        Sessions(session),
        FakeWorkspaceOwnershipQueryAdapter(),
        audit,
        schedule,
        now=lambda: now,
    ).execute(account.account_id, session.session_id)
    assert account.status is AccountStatus.DELETION_PENDING and schedule.scheduled[0][
        1
    ] == now + timedelta(days=30)
    await CancelAccountDeletion(
        Accounts(account), audit, schedule, now=lambda: now
    ).execute(account.account_id)
    assert account.status is AccountStatus.ACTIVE


@pytest.mark.asyncio
async def test_deletion_blocks_sole_owner_and_requires_recent_auth():
    now = datetime.now(UTC)
    account = Account.create_with_email("a@example.com", at=now)
    session = Session.create(
        account_id=account.account_id, device_id="d", at=now - timedelta(minutes=11)
    )
    with pytest.raises(AuthenticationError) as error:
        await RequestAccountDeletion(
            Accounts(account),
            Sessions(session),
            FakeWorkspaceOwnershipQueryAdapter(),
            Audit(),
            Schedule(),
            now=lambda: now,
        ).execute(account.account_id, session.session_id)
    assert error.value.error_code == "RECENT_AUTHENTICATION_REQUIRED"
    session.reauthenticate(now)
    ownership = FakeWorkspaceOwnershipQueryAdapter()
    ownership.set_sole_ownership(account.account_id, "设计组")
    with pytest.raises(ConflictError) as error:
        await RequestAccountDeletion(
            Accounts(account),
            Sessions(session),
            ownership,
            Audit(),
            Schedule(),
            now=lambda: now,
        ).execute(account.account_id, session.session_id)
    assert error.value.error_code == "ACCOUNT_DELETION_SOLE_OWNER"
    assert error.value.category == "Conflict"
    assert (
        error.value.message
        == "您是工作区 设计组 的唯一所有者，请先转让所有权或解散工作区后再申请注销账号"
    )


@pytest.mark.asyncio
async def test_deletion_sole_owner_without_name_uses_fallback_message():
    now = datetime.now(UTC)
    account = Account.create_with_email("unnamed@example.com", at=now)
    session = Session.create(account_id=account.account_id, device_id="d", at=now)
    session.reauthenticate(now)
    ownership = FakeWorkspaceOwnershipQueryAdapter()
    ownership.set_sole_ownership(account.account_id, "")
    with pytest.raises(ConflictError) as error:
        await RequestAccountDeletion(
            Accounts(account),
            Sessions(session),
            ownership,
            Audit(),
            Schedule(),
            now=lambda: now,
        ).execute(account.account_id, session.session_id)
    assert error.value.error_code == "ACCOUNT_DELETION_SOLE_OWNER"
    assert (
        error.value.message == "您是某个未删除工作区的唯一所有者，"
        "请先转让所有权或解散工作区后再申请注销账号"
    )


@pytest.mark.asyncio
async def test_purge_after_grace_deletes_revokes_sessions_and_completes_request():
    now = datetime.now(UTC)
    account = Account.create_with_email("a@example.com", at=now)
    account.request_deletion(now - timedelta(days=30))
    sessions = Sessions(None)
    deletion = Deletion()
    await ProcessAccountPurge(
        Accounts(account), sessions, Audit(), deletion, now=lambda: now
    ).execute(account.account_id)
    assert account.status is AccountStatus.DELETED and sessions.revoked == [
        (account.account_id, "AccountDeleted")
    ]
    assert deletion.completed == [(account.account_id, now)]


@pytest.mark.asyncio
async def test_deletion_rejects_cross_account_session():
    now = datetime.now(UTC)
    account = Account.create_with_email("target@example.com", at=now)
    other = Account.create_with_email("other@example.com", at=now)
    session = Session.create(account_id=other.account_id, device_id="d", at=now)
    session.reauthenticate(now)
    with pytest.raises(AuthenticationError) as error:
        await RequestAccountDeletion(
            Accounts(account),
            Sessions(session),
            FakeWorkspaceOwnershipQueryAdapter(),
            Audit(),
            Schedule(),
            now=lambda: now,
        ).execute(account.account_id, session.session_id)
    assert error.value.error_code == "SESSION_NOT_AUTHORIZED"


@pytest.mark.asyncio
async def test_deletion_rejects_inactive_or_expired_session():
    now = datetime.now(UTC)
    account = Account.create_with_email("target@example.com", at=now)
    session = Session.create(account_id=account.account_id, device_id="d", at=now)
    session.reauthenticate(now)
    session.replace(account.account_id, now)
    with pytest.raises(AuthenticationError) as error:
        await RequestAccountDeletion(
            Accounts(account),
            Sessions(session),
            FakeWorkspaceOwnershipQueryAdapter(),
            Audit(),
            Schedule(),
            now=lambda: now,
        ).execute(account.account_id, session.session_id)
    assert error.value.error_code == "SESSION_NOT_AUTHORIZED"


@pytest.mark.asyncio
async def test_purge_before_grace_raises_purge_not_due():
    now = datetime.now(UTC)
    account = Account.create_with_email("early@example.com", at=now)
    account.request_deletion(now - timedelta(days=1))
    with pytest.raises(ValidationError) as error:
        await ProcessAccountPurge(
            Accounts(account), Sessions(None), Audit(), Deletion(), now=lambda: now
        ).execute(account.account_id)
    assert error.value.error_code == "PURGE_NOT_DUE"


@pytest.mark.asyncio
async def test_purge_without_pending_request_raises_purge_not_due():
    now = datetime.now(UTC)
    account = Account.create_with_email("none@example.com", at=now)
    with pytest.raises(ValidationError) as error:
        await ProcessAccountPurge(
            Accounts(account), Sessions(None), Audit(), Deletion(), now=lambda: now
        ).execute(account.account_id)
    assert error.value.error_code == "PURGE_NOT_DUE"


@pytest.mark.asyncio
async def test_cancel_deletion_for_missing_account_raises_not_found():
    now = datetime.now(UTC)
    with pytest.raises(NotFoundError) as error:
        await CancelAccountDeletion(
            Accounts(None), Audit(), Schedule(), now=lambda: now
        ).execute(uuid4())
    assert error.value.error_code == "ACCOUNT_NOT_FOUND"


@pytest.mark.asyncio
async def test_repeated_deletion_request_does_not_reschedule_or_duplicate_audit():
    now = datetime.now(UTC)
    account = Account.create_with_email("retry@example.com", at=now)
    account.verify_email(now)
    session = Session.create(account_id=account.account_id, device_id="d", at=now)
    session.reauthenticate(now)
    accounts, sessions, ownership, audit, schedule = (
        Accounts(account),
        Sessions(session),
        FakeWorkspaceOwnershipQueryAdapter(),
        Audit(),
        Schedule(),
    )
    use_case = RequestAccountDeletion(
        accounts, sessions, ownership, audit, schedule, now=lambda: now
    )
    await use_case.execute(account.account_id, session.session_id)
    original = account.deletion_requested_at
    await use_case.execute(account.account_id, session.session_id)
    assert (
        account.deletion_requested_at == original
        and len(schedule.scheduled) == 1
        and audit.actions == ["AccountDeletionRequested"]
    )
