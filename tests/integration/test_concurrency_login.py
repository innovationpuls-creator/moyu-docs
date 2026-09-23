"""Phase 9 Task 28: concurrent logins converge to the 2-device quota.

Review Focus #4 / FR-AUTH-012, FR-AUTH-014, FR-AUTH-015 + Constitution #59:

- 5 concurrent login requests for one account on distinct devices (real
  Postgres COMMIT per request) must leave exactly 2 Active sessions and
  replace the 3 sessions with the oldest (created_at, session_id) ordering.
- zero deadlocks: create_device_session_atomically serializes the critical
  section on the account row via SELECT ... FOR UPDATE (a single shared lock
  -> no lock cycle), so asyncio.gather must not surface any exception.
- every replaced session emits exactly one integration.outbox_events
  SessionReplaced row (consistency with the authoritative session table).

Design notes: each login runs in its own AsyncSession from the real engine
pool (pool_size=10) and COMMITs, so transaction N sees the committed effects
of transaction N-1 under READ COMMITTED. No retry wrapper is needed because
the account-row lock makes deadlocks structurally impossible (single-lock
serialization); the test asserts that by gathering without swallowing errors.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from uuid import uuid4

from app_core.account.domain.account import Account
from app_core.account.domain.password_policy import PasswordHasher
from app_core.session.application.authentication import LoginResult
from app_core.session.domain.session import SessionStatus
from app_infra.postgres.account_repository import PostgresAccountRepository
from app_infra.postgres.engine import async_session_factory, engine
from app_infra.postgres.registration_composition import build_login_use_case
from sqlalchemy import text

VALID_PASSWORD = "Str0ng#Passw0rd"


async def test_five_concurrent_logins_distinct_devices_leave_two_active(
    migrated_database: None,
    cleanup_accounts: list[str],
) -> None:
    email = f"concurrent-{uuid4().hex[:12]}@example.com"
    cleanup_accounts.append(email)

    # Seed a real committed account with a password credential.
    async with async_session_factory() as seeding:
        account = Account.create_with_email(email, at=datetime.now(timezone.utc))
        await PostgresAccountRepository(seeding).save(
            account, PasswordHasher.hash(VALID_PASSWORD)
        )
        await seeding.commit()
    account_id = account.account_id

    async def _login(device_id: str) -> LoginResult:
        async with async_session_factory() as session:
            use_case = build_login_use_case(session)
            result = await use_case.execute(email, VALID_PASSWORD, device_id)
            await session.commit()
            return result

    results = await asyncio.gather(*(_login(f"device-{index}") for index in range(5)))

    # Zero deadlocks / serialization failures surfaced.
    assert len(results) == 5
    for result in results:
        assert result.session.status is SessionStatus.ACTIVE

    # Authoritative Postgres state: 2 Active, 3 Replaced; the replaced are the
    # 3 sessions with the oldest (created_at, session_id) ordering.
    async with engine.connect() as connection:
        rows = (
            (
                await connection.execute(
                    text(
                        "SELECT session_id, status FROM auth.sessions "
                        "WHERE account_id = :account_id "
                        "ORDER BY created_at, session_id"
                    ),
                    {"account_id": account_id},
                )
            )
            .mappings()
            .all()
        )

    assert len(rows) == 5
    active_ids = [row["session_id"] for row in rows if row["status"] == "Active"]
    replaced_ids = [row["session_id"] for row in rows if row["status"] == "Replaced"]
    assert len(active_ids) == 2
    assert len(replaced_ids) == 3
    assert replaced_ids == [row["session_id"] for row in rows[:3]]
    assert active_ids == [row["session_id"] for row in rows[3:]]

    # Outbox consistency: exactly one SessionReplaced row per replaced session.
    async with engine.connect() as connection:
        outbox = (
            (
                await connection.execute(
                    text(
                        "SELECT o.aggregate_id, o.event_type FROM "
                        "integration.outbox_events o "
                        "JOIN auth.sessions s ON s.session_id = o.aggregate_id "
                        "WHERE s.account_id = :account_id "
                        "AND o.event_type = 'SessionReplaced'"
                    ),
                    {"account_id": account_id},
                )
            )
            .mappings()
            .all()
        )
    assert [row["aggregate_id"] for row in outbox] == replaced_ids
