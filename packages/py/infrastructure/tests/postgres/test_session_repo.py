from __future__ import annotations

import json
from collections.abc import AsyncIterator
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

import jsonschema
import pytest
import pytest_asyncio
from app_core.account.domain.account import Account
from app_core.account.domain.password_policy import PasswordHasher
from app_core.common.exceptions import AuthenticationError
from app_core.session.application.authentication import (
    LoginWithPassword,
    Reauthenticate,
)
from app_core.session.domain.session import (
    Session,
    SessionInvalidationReason,
    SessionStatus,
)
from app_infra.postgres.account_repository import PostgresAccountRepository
from app_infra.postgres.engine import engine
from app_infra.postgres.registration_composition import build_login_use_case
from app_infra.postgres.session_repository import PostgresSessionRepository
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

pytestmark = pytest.mark.filterwarnings(
    "ignore:jsonschema.RefResolver is deprecated:DeprecationWarning"
)


@pytest_asyncio.fixture
async def db_session() -> AsyncIterator[AsyncSession]:
    async with engine.connect() as connection:
        transaction = await connection.begin()
        factory = async_sessionmaker(
            bind=connection,
            expire_on_commit=False,
            class_=AsyncSession,
            join_transaction_mode="create_savepoint",
        )
        async with factory() as session:
            try:
                yield session
            finally:
                await session.rollback()
                await transaction.rollback()


@pytest.mark.asyncio
async def test_atomic_three_device_replacement_uses_created_at_and_writes_outbox(
    db_session: AsyncSession,
) -> None:
    account_id = uuid4()
    await db_session.execute(
        text(
            "INSERT INTO auth.accounts "
            "(account_id, status, primary_email, normalized_email) "
            "VALUES (:account_id, 'Active', :email, :email)"
        ),
        {"account_id": account_id, "email": f"{account_id}@example.com"},
    )
    repository = PostgresSessionRepository(db_session)
    t1 = datetime(2026, 9, 22, 10, tzinfo=timezone.utc)
    t2 = t1 + timedelta(hours=1)
    t3 = t2 + timedelta(hours=1)
    first = Session.create(
        account_id=account_id,
        device_id="device-1",
        at=t1,
        last_seen_at=t1 + timedelta(minutes=90),
    )
    second = Session.create(account_id=account_id, device_id="device-2", at=t2)
    incoming = Session.create(account_id=account_id, device_id="device-3", at=t3)

    _, replaced1 = await repository.create_device_session_atomically(
        account_id, "device-1", first
    )
    _, replaced2 = await repository.create_device_session_atomically(
        account_id, "device-2", second
    )
    _, replaced3 = await repository.create_device_session_atomically(
        account_id, "device-3", incoming
    )

    assert replaced1 == []
    assert replaced2 == []
    assert [session.session_id for session in replaced3] == [first.session_id]
    first_db = await repository.find_by_id(first.session_id)
    second_db = await repository.find_by_id(second.session_id)
    incoming_db = await repository.find_by_id(incoming.session_id)
    assert first_db is not None
    assert second_db is not None
    assert incoming_db is not None
    assert first_db.status is SessionStatus.REPLACED
    assert second_db.status is SessionStatus.ACTIVE
    assert incoming_db.status is SessionStatus.ACTIVE

    outbox = await db_session.execute(
        text(
            "SELECT event_id, event_type, schema_version, aggregate_type, "
            "aggregate_id, payload FROM integration.outbox_events "
            "WHERE aggregate_id = :aggregate_id"
        ),
        {"aggregate_id": first.session_id},
    )
    row = outbox.mappings().one()
    assert row["event_type"] == "SessionReplaced"
    assert row["schema_version"] == "1.0.0"
    assert row["aggregate_type"] == "Session"
    schema = json.loads(
        Path("contracts/events/auth/session-replaced.schema.json").read_text()
    )
    ids_schema = json.loads(Path("contracts/ids/ids.schema.json").read_text())
    resolver = jsonschema.RefResolver(
        base_uri=schema["$id"],
        referrer=schema,
        store={ids_schema["$id"]: ids_schema},
    )
    jsonschema.Draft202012Validator(schema, resolver=resolver).validate(row["payload"])
    assert row["payload"]["eventId"] == str(row["event_id"])
    assert row["payload"]["eventType"] == "SessionReplaced"
    assert row["payload"]["producer"] == "services.api"
    assert row["payload"]["payload"] == {
        "userId": str(account_id),
        "replacedSessionId": str(first.session_id),
        "replacedBySessionId": str(incoming.session_id),
        "invalidationReason": "NewDeviceLogin",
        "replacedAt": row["payload"]["payload"]["replacedAt"],
    }

    audit = await db_session.execute(
        text(
            "SELECT action, actor_type, actor_id, target_ref, metadata "
            "FROM audit.entries WHERE actor_id = :actor_id "
            "AND action = 'SessionReplaced'"
        ),
        {"actor_id": account_id},
    )
    audit_row = audit.mappings().one()
    assert audit_row["action"] == "SessionReplaced"
    assert audit_row["actor_type"] == "Account"
    assert audit_row["target_ref"]["sessionId"] == str(first.session_id)
    assert audit_row["target_ref"]["deviceId"] == "device-1"
    assert audit_row["metadata"] == {"invalidationReason": "NewDeviceLogin"}


@pytest.mark.asyncio
async def test_same_device_relogin_replaces_old_and_distinct_device_quota_bounds(
    db_session: AsyncSession,
) -> None:
    account_id = uuid4()
    await db_session.execute(
        text(
            "INSERT INTO auth.accounts "
            "(account_id, status, primary_email, normalized_email) "
            "VALUES (:account_id, 'Active', :email, :email)"
        ),
        {"account_id": account_id, "email": f"{account_id}@example.com"},
    )
    repository = PostgresSessionRepository(db_session)
    t1 = datetime(2026, 9, 22, 10, tzinfo=timezone.utc)
    t2 = t1 + timedelta(hours=1)
    t3 = t2 + timedelta(hours=1)
    first = Session.create(account_id=account_id, device_id="device-1", at=t1)
    second = Session.create(account_id=account_id, device_id="device-1", at=t2)
    third = Session.create(account_id=account_id, device_id="device-2", at=t3)

    _, replaced1 = await repository.create_device_session_atomically(
        account_id, "device-1", first
    )
    _, replaced2 = await repository.create_device_session_atomically(
        account_id, "device-1", second
    )
    _, replaced3 = await repository.create_device_session_atomically(
        account_id, "device-2", third
    )

    assert replaced1 == []
    assert [session.session_id for session in replaced2] == [first.session_id]
    assert replaced3 == []
    first_db = await repository.find_by_id(first.session_id)
    second_db = await repository.find_by_id(second.session_id)
    third_db = await repository.find_by_id(third.session_id)
    assert first_db is not None
    assert second_db is not None
    assert third_db is not None
    assert first_db.status is SessionStatus.REPLACED
    assert first_db.invalidation_reason == "NewDeviceLogin"
    assert first_db.replaced_by_session_id == second.session_id
    assert second_db.status is SessionStatus.ACTIVE
    assert third_db.status is SessionStatus.ACTIVE


@pytest.mark.asyncio
async def test_login_persists_auto_expired_session_transition_in_same_transaction(
    db_session: AsyncSession,
) -> None:
    account_id = uuid4()
    now = datetime(2026, 9, 22, 10, tzinfo=timezone.utc)
    await db_session.execute(
        text(
            "INSERT INTO auth.accounts "
            "(account_id, status, primary_email, normalized_email) "
            "VALUES (:account_id, 'Active', :email, :email)"
        ),
        {"account_id": account_id, "email": f"{account_id}@example.com"},
    )
    old_session_id = uuid4()
    await db_session.execute(
        text(
            "INSERT INTO auth.sessions "
            "(session_id, account_id, device_id, status, session_version, "
            "last_strong_auth_at, created_at, last_seen_at, expires_at) "
            "VALUES (:session_id, :account_id, 'old-device', 'Active', 1, "
            ":last_strong_auth_at, :created_at, :last_seen_at, :expires_at)"
        ),
        {
            "session_id": old_session_id,
            "account_id": account_id,
            "last_strong_auth_at": now - timedelta(days=91),
            "created_at": now - timedelta(days=91),
            "last_seen_at": now - timedelta(days=91),
            "expires_at": now - timedelta(seconds=1),
        },
    )
    repository = PostgresSessionRepository(db_session)
    incoming = Session.create(account_id=account_id, device_id="new-device", at=now)
    new_session, replaced = await repository.create_device_session_atomically(
        account_id, "new-device", incoming
    )

    assert replaced == []
    assert new_session.session_id == incoming.session_id
    expiration_row = (
        (
            await db_session.execute(
                text(
                    "SELECT status, invalidation_reason, replaced_at "
                    "FROM auth.sessions WHERE session_id = :session_id"
                ),
                {"session_id": old_session_id},
            )
        )
        .mappings()
        .one()
    )
    assert expiration_row["status"] == "Expired"
    assert expiration_row["invalidation_reason"] == "Expired"
    hydrated = await repository.find_by_id(old_session_id)
    assert hydrated is not None
    assert hydrated.status is SessionStatus.EXPIRED
    assert hydrated.invalidation_reason is SessionInvalidationReason.EXPIRED
    assert hydrated.invalidated_at is not None
    active_count = await db_session.scalar(
        text(
            "SELECT count(*) FROM auth.sessions "
            "WHERE account_id = :account_id AND status = 'Active'"
        ),
        {"account_id": account_id},
    )
    assert active_count == 1
    assert active_count <= 2


@pytest.mark.asyncio
async def test_mark_logged_out_is_idempotent_and_revoke_all_returns_ids(
    db_session: AsyncSession,
) -> None:
    account_id = uuid4()
    await db_session.execute(
        text(
            "INSERT INTO auth.accounts "
            "(account_id, status, primary_email, normalized_email) "
            "VALUES (:account_id, 'Active', :email, :email)"
        ),
        {"account_id": account_id, "email": f"{account_id}@example.com"},
    )
    repository = PostgresSessionRepository(db_session)
    now = datetime(2026, 9, 22, tzinfo=timezone.utc)
    first = Session.create(account_id=account_id, device_id="device-1", at=now)
    second = Session.create(account_id=account_id, device_id="device-2", at=now)
    await repository.create_device_session_atomically(account_id, "device-1", first)
    await repository.create_device_session_atomically(account_id, "device-2", second)

    await repository.mark_logged_out(first.session_id)
    await repository.mark_logged_out(first.session_id)
    revoked = await repository.revoke_all_sessions(account_id, "PasswordReset")

    first_db = await repository.find_by_id(first.session_id)
    second_db = await repository.find_by_id(second.session_id)
    assert revoked == [second.session_id]
    assert first_db is not None
    assert second_db is not None
    assert first_db.status is SessionStatus.LOGGED_OUT
    assert second_db.status is SessionStatus.REVOKED


@pytest.mark.asyncio
async def test_updates_last_strong_auth_for_active_session(
    db_session: AsyncSession,
) -> None:
    account_id = uuid4()
    await db_session.execute(
        text(
            "INSERT INTO auth.accounts "
            "(account_id, status, primary_email, normalized_email) "
            "VALUES (:account_id, 'Active', :email, :email)"
        ),
        {"account_id": account_id, "email": f"{account_id}@example.com"},
    )
    repository = PostgresSessionRepository(db_session)
    created_at = datetime(2026, 9, 22, tzinfo=timezone.utc)
    session = Session.create(account_id=account_id, device_id="device-1", at=created_at)
    await repository.create_device_session_atomically(account_id, "device-1", session)
    reauthenticated_at = created_at + timedelta(minutes=5)
    session.reauthenticate(reauthenticated_at)

    await repository.update_last_strong_auth(session)

    restored = await repository.find_by_id(session.session_id)
    assert restored is not None
    assert restored.last_strong_auth_at == reauthenticated_at


@pytest.mark.asyncio
async def test_login_application_uses_postgres_repositories_and_persists_reauth(
    db_session: AsyncSession,
) -> None:
    now = datetime(2026, 9, 22, tzinfo=timezone.utc)
    account = Account.create_with_email("Alice@Example.com", at=now)
    account.verify_email(at=now)
    accounts = PostgresAccountRepository(db_session)
    sessions = PostgresSessionRepository(db_session)
    await accounts.save(account, PasswordHasher.hash("A unique passphrase 2026"))
    login = LoginWithPassword(accounts, sessions, now=lambda: now)

    with pytest.raises(AuthenticationError, match="Invalid credentials"):
        await login.execute("alice@example.com", "wrong password", "wrong-device")
    session_count = await db_session.scalar(
        text("SELECT count(*) FROM auth.sessions WHERE account_id = :account_id"),
        {"account_id": account.account_id},
    )
    assert session_count == 0

    first = await login.execute(
        "  ALICE@example.com ", "A unique passphrase 2026", "device-1"
    )
    second = await login.execute(
        "alice@example.com", "A unique passphrase 2026", "device-2"
    )
    assert first.session.account_id == account.account_id
    assert second.session.account_id == account.account_id
    active_count = await db_session.scalar(
        text(
            "SELECT count(*) FROM auth.sessions "
            "WHERE account_id = :account_id AND status = 'Active'"
        ),
        {"account_id": account.account_id},
    )
    assert active_count == 2

    reauthenticated_at = now + timedelta(minutes=5)
    reauthenticated = await Reauthenticate(
        accounts, sessions, now=lambda: reauthenticated_at
    ).execute(first.session.session_id, "A unique passphrase 2026")
    restored = await sessions.find_by_id(first.session.session_id)
    assert restored is not None
    assert reauthenticated.last_strong_auth_at == reauthenticated_at
    assert restored.last_strong_auth_at == reauthenticated_at


@pytest.mark.asyncio
async def test_login_idempotency_same_key_replays_same_session(
    db_session: AsyncSession,
) -> None:
    now = datetime(2026, 9, 22, tzinfo=timezone.utc)
    account = Account.create_with_email("Alice@Example.com", at=now)
    account.verify_email(at=now)
    accounts = PostgresAccountRepository(db_session)
    await accounts.save(account, PasswordHasher.hash("A unique passphrase 2026"))
    login = build_login_use_case(db_session, now=lambda: now)
    key = f"login-{uuid4()}"

    first = await login.execute(
        "alice@example.com", "A unique passphrase 2026", "device-1", idempotency_key=key
    )
    replay = await login.execute(
        "alice@example.com", "A unique passphrase 2026", "device-1", idempotency_key=key
    )

    assert replay.session.session_id == first.session.session_id
    assert replay.account.account_id == first.account.account_id
    active_count = await db_session.scalar(
        text(
            "SELECT count(*) FROM auth.sessions "
            "WHERE account_id = :account_id AND status = 'Active'"
        ),
        {"account_id": account.account_id},
    )
    assert active_count == 1


@pytest.mark.asyncio
async def test_login_idempotency_distinct_keys_create_two_active_sessions(
    db_session: AsyncSession,
) -> None:
    now = datetime(2026, 9, 22, tzinfo=timezone.utc)
    account = Account.create_with_email("Alice@Example.com", at=now)
    account.verify_email(at=now)
    accounts = PostgresAccountRepository(db_session)
    await accounts.save(account, PasswordHasher.hash("A unique passphrase 2026"))
    login = build_login_use_case(db_session, now=lambda: now)

    first = await login.execute(
        "alice@example.com",
        "A unique passphrase 2026",
        "device-1",
        idempotency_key=f"k-{uuid4()}",
    )
    second = await login.execute(
        "alice@example.com",
        "A unique passphrase 2026",
        "device-2",
        idempotency_key=f"k-{uuid4()}",
    )

    assert second.session.session_id != first.session.session_id
    active_count = await db_session.scalar(
        text(
            "SELECT count(*) FROM auth.sessions "
            "WHERE account_id = :account_id AND status = 'Active'"
        ),
        {"account_id": account.account_id},
    )
    assert active_count == 2
