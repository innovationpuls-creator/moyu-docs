"""Phase 9 Task 28: concurrent same-email registration converges to ONE account.

Review Focus #1 / BDD scenario 14 + FR-AUTH-005, PRD cross-requirement
invariant 6: concurrent registrations for one email must never create a
duplicate account, and every caller receives the uniform anti-enumeration
result (the 201 REGISTER_SUCCESS body at the API boundary; `session is None`
exactly for the losers, which never mint a session, FR-AUTH-005).

Concurrency design: each registration runs in its own committed transaction.
Exactly one caller wins the unique index on auth.accounts.normalized_email;
the losers either (a) observe the committed winner via find_by_email (uniform
pre-check branch) or (b) hit the unique-index IntegrityError that
PostgresAccountRepository.save maps to DuplicateEmailError, which RegisterAccount
maps to the same uniform result (task-5 Item 6 / plan Task 12). There is no
lock cycle: the blocked INSERT simply waits on the winner's unique-index entry,
so no deadlock wrapper is needed. A deterministic repository-level test covers
the unique-index loser path directly.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from uuid import uuid4

import pytest
from app_core.account.application.registration import RegistrationResult
from app_core.account.domain.account import Account
from app_core.account.domain.password_policy import PasswordHasher
from app_core.common.exceptions import DuplicateEmailError
from app_infra.postgres.account_repository import PostgresAccountRepository
from app_infra.postgres.engine import async_session_factory, engine
from app_infra.postgres.registration_composition import build_registration_use_case
from sqlalchemy import text

VALID_PASSWORD = "Str0ng#Passw0rd"


class CapturingMailer:
    """Dev mailer: records (email, secret) instead of sending."""

    def __init__(self) -> None:
        self.sent: list[tuple[str, str]] = []

    async def send_verification(self, email: str, secret: str) -> None:
        self.sent.append((email, secret))


def _now() -> datetime:
    return datetime.now(timezone.utc)


async def _account_count(email: str) -> int:
    async with engine.connect() as connection:
        count = await connection.scalar(
            text("SELECT count(*) FROM auth.accounts WHERE normalized_email = :email"),
            {"email": email.strip().casefold()},
        )
        return int(count or 0)


async def _session_count_for_email(email: str) -> int:
    async with engine.connect() as connection:
        count = await connection.scalar(
            text(
                "SELECT count(*) FROM auth.sessions s "
                "JOIN auth.accounts a ON a.account_id = s.account_id "
                "WHERE a.normalized_email = :email"
            ),
            {"email": email.strip().casefold()},
        )
        return int(count or 0)


async def test_concurrent_same_email_registrations_converge_to_single_account(
    migrated_database: None,
    cleanup_accounts: list[str],
) -> None:
    email = f"race-{uuid4().hex[:12]}@example.com"
    cleanup_accounts.append(email)
    mailer = CapturingMailer()

    async def _register(device_id: str) -> RegistrationResult:
        async with async_session_factory() as session:
            use_case = build_registration_use_case(session, mailer, now=_now)
            result = await use_case.execute(email, VALID_PASSWORD, device_id)
            if result.session is not None:
                await session.commit()  # only the winner commits
            else:
                # Loser path: either branch (pre-check or DuplicateEmailError)
                # produced the uniform result; roll back (already rolled back
                # in the IntegrityError branch) and close.
                await session.rollback()
            return result

    results = await asyncio.gather(*(_register(f"device-{i}") for i in range(4)))

    # Every caller received the uniform anti-enumeration result, no exceptions.
    assert len(results) == 4
    winners = [result for result in results if result.session is not None]
    losers = [result for result in results if result.session is None]
    assert len(winners) == 1
    assert len(losers) == 3
    messages = {result.public_message for result in results}
    assert len(messages) == 1  # uniform message across winner and losers
    assert all(result.accepted for result in results)
    assert all(result.verification_secret is None for result in losers)

    # Converged to exactly one committed account and one session (the winner).
    assert await _account_count(email) == 1
    assert await _session_count_for_email(email) == 1
    assert len(mailer.sent) == 1  # only the winner queued a verification mail


async def test_unique_index_loser_maps_to_duplicate_email_error(
    migrated_database: None,
    cleanup_accounts: list[str],
) -> None:
    """Deterministic repository-level coverage of the IntegrityError ->
    DuplicateEmailError mapping (the losers' concurrent branch)."""
    email = f"race-deterministic-{uuid4().hex[:12]}@example.com"
    cleanup_accounts.append(email)

    async with async_session_factory() as seeding:
        first = Account.create_with_email(email, at=datetime.now(timezone.utc))
        await PostgresAccountRepository(seeding).save(
            first, PasswordHasher.hash(VALID_PASSWORD)
        )
        await seeding.commit()

    second = Account.create_with_email(email, at=datetime.now(timezone.utc))
    async with async_session_factory() as losing:
        with pytest.raises(DuplicateEmailError):
            await PostgresAccountRepository(losing).save(
                second, PasswordHasher.hash(VALID_PASSWORD)
            )
        await losing.rollback()

    assert await _account_count(email) == 1


async def test_registration_race_loser_receives_uniform_use_case_result(
    migrated_database: None,
    cleanup_accounts: list[str],
) -> None:
    """Deterministic use-case fallback: a registration against an already
    committed email returns the SAME uniform message as a fresh registration
    (no exception, no session, no duplicate row) — the API boundary renders
    both as 201 REGISTER_SUCCESS (USER RULING)."""
    email = f"race-uniform-{uuid4().hex[:12]}@example.com"
    cleanup_accounts.append(email)
    mailer = CapturingMailer()

    async with async_session_factory() as seeding:
        account = Account.create_with_email(email, at=datetime.now(timezone.utc))
        await PostgresAccountRepository(seeding).save(
            account, PasswordHasher.hash(VALID_PASSWORD)
        )
        await seeding.commit()

    async with async_session_factory() as session:
        use_case = build_registration_use_case(session, mailer, now=_now)
        loser = await use_case.execute(email, VALID_PASSWORD, "device-loser")
        await session.rollback()

    # The fresh path sends a mail; the "loser" path is uniform and silent.
    fresh_email = f"{email}.fresh"
    cleanup_accounts.append(fresh_email)
    async with async_session_factory() as session:
        use_case = build_registration_use_case(session, mailer, now=_now)
        winner = await use_case.execute(fresh_email, VALID_PASSWORD, "device-winner")
        await session.commit()

    assert loser.accepted is True
    assert loser.session is None
    assert loser.verification_secret is None
    assert loser.public_message == winner.public_message
    assert await _account_count(email) == 1
    assert await _session_count_for_email(email) == 0
    assert len(mailer.sent) == 1
