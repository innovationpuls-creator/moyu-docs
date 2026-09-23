"""Plan Task 24: delete-account / cancel-delete-account / status + recovery guard.

BDD-aligned scenarios (docs/behavior/features/account-auth-session.feature):
- FR-AUTH-029: delete blocked with 409 ACCOUNT_DELETION_SOLE_OWNER when the
  account is the sole owner of a workspace (exact BDD message); requires a
  10-minute recent auth window (401 RECENT_AUTHENTICATION_REQUIRED).
- FR-AUTH-030: delete -> DeletionPending + grace period fields; GET
  /v1/auth/status reports remaining grace days and executeAfter.
- FR-AUTH-031: cancel restores the pre-deletion status; cancel when not in
  deletion -> 409 ACCOUNT_NOT_IN_DELETION.
- FR-AUTH-032: recovery-mode guard blocks non-recovery endpoints
  (/v1/auth/me, /v1/auth/session) with 403 for a DeletionPending account while
  deletion endpoints (status / cancel) stay reachable.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from uuid import UUID

import pytest
from api.dependencies.auth import get_db_session, get_valkey
from api.dependencies.workspace_ownership import (
    WorkspaceOwnershipQueryPort,
    get_workspace_ownership,
)
from api.main import create_app
from api.routes.auth_deletion import _deletion_pending_response
from app_core.account.domain.account import Account, AccountStatus
from app_core.common.exceptions import NotFoundError
from app_infra.postgres.account_repository import PostgresAccountRepository
from app_infra.postgres.idempotency_repository import PostgresIdempotencyRepository
from httpx import ASGITransport, AsyncClient
from redis.asyncio import Redis
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

VALID_PASSWORD = "Str0ng#Passw0rd"


class SoleOwnerWorkspaceQuery(WorkspaceOwnershipQueryPort):
    """Test adapter reporting the account as the sole owner of a named
    workspace (dependency-overridable replacement for the production
    no-owner adapter; mirrors FakeWorkspaceOwnershipQueryAdapter)."""

    def __init__(self, workspace_name: str) -> None:
        self._name = workspace_name

    async def has_sole_workspace_ownership(
        self, account_id: UUID
    ) -> tuple[bool, str | None]:
        return True, self._name


@asynccontextmanager
async def _client(
    db_session: AsyncSession,
    valkey_client: Redis,
    ownership: WorkspaceOwnershipQueryPort | None = None,
) -> AsyncIterator[AsyncClient]:
    app = create_app(debug=True)
    app.dependency_overrides[get_db_session] = lambda: db_session
    app.dependency_overrides[get_valkey] = lambda: valkey_client
    if ownership is not None:
        app.dependency_overrides[get_workspace_ownership] = lambda: ownership
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        yield client


async def _register(client: AsyncClient, email: str) -> dict[str, object]:
    response = await client.post(
        "/v1/auth/register", json={"email": email, "password": VALID_PASSWORD}
    )
    assert response.status_code == 201
    return response.json()


async def _make_active(db_session: AsyncSession, email: str) -> UUID:
    """Register + verify -> Active account; returns the account id."""
    accounts = PostgresAccountRepository(db_session)
    record = await accounts.find_by_email(email)
    assert record is not None
    record.account.verify_email()
    await accounts.update(record.account)
    return record.account.account_id


async def _account_status(db_session: AsyncSession, account_id: UUID) -> str | None:
    return await db_session.scalar(
        text("SELECT status FROM auth.accounts WHERE account_id = :id"),
        {"id": account_id},
    )


# ---------------------------------------------------------------------------
# POST /v1/auth/delete-account
# ---------------------------------------------------------------------------


async def test_delete_account_enters_deletion_pending_with_grace_fields(
    db_session: AsyncSession,
    valkey_client: Redis,
) -> None:
    async with _client(db_session, valkey_client) as client:
        await _register(client, "del@example.com")
        # Make the account Active (verified) so the pre-deletion state is Active.
        account_id = await _make_active(db_session, "del@example.com")

        response = await client.post("/v1/auth/delete-account")

    assert response.status_code == 200
    body = response.json()
    assert body["messageKey"] == "DELETION_REQUESTED"
    assert body["accountStatus"] == "DeletionPending"
    assert body["gracePeriodDaysRemaining"] == 30
    requested = datetime.fromisoformat(body["deletionRequestedAt"])
    execute_after = datetime.fromisoformat(body["executeAfter"])
    assert execute_after - requested == timedelta(days=30)
    assert await _account_status(db_session, account_id) == "DeletionPending"


async def test_delete_account_blocked_for_sole_workspace_owner(
    db_session: AsyncSession,
    valkey_client: Redis,
) -> None:
    ownership = SoleOwnerWorkspaceQuery("Workspace_Alpha")
    async with _client(db_session, valkey_client, ownership=ownership) as client:
        await _register(client, "owner@example.com")
        account_id = await _make_active(db_session, "owner@example.com")

        response = await client.post("/v1/auth/delete-account")

    assert response.status_code == 409
    body = response.json()
    assert body["category"] == "Conflict"
    assert body["errorCode"] == "ACCOUNT_DELETION_SOLE_OWNER"
    assert body["messageKey"] == "auth.error.accountDeletionSoleOwner"
    assert (
        body["message"] == "您是工作区 Workspace_Alpha 的唯一所有者，"
        "请先转让所有权或解散工作区后再申请注销账号"
    )
    assert await _account_status(db_session, account_id) == "Active"


async def test_delete_account_requires_recent_authentication(
    db_session: AsyncSession,
    valkey_client: Redis,
) -> None:
    async with _client(db_session, valkey_client) as client:
        await _register(client, "stale@example.com")
        await _make_active(db_session, "stale@example.com")
        # Age the current session's recent-auth so the window (10 min) has passed.
        await db_session.execute(
            text(
                "UPDATE auth.sessions SET last_strong_auth_at = :at "
                "WHERE status = 'Active'"
            ),
            {"at": datetime.now(timezone.utc) - timedelta(minutes=11)},
        )
        await db_session.flush()

        response = await client.post("/v1/auth/delete-account")

    assert response.status_code == 401
    body = response.json()
    assert body["errorCode"] == "RECENT_AUTHENTICATION_REQUIRED"
    assert body["messageKey"] == "auth.error.recentAuthenticationRequired"


# ---------------------------------------------------------------------------
# Idempotency (registry idempotencyRequirement: required) + invariant handling
# ---------------------------------------------------------------------------


def test_deletion_response_without_requested_at_raises_not_found() -> None:
    """Item 4 (minor): the production `assert account.deletion_requested_at is
    not None` is replaced by an explicit NotFoundError so the route never
    crashes under -O nor emits a DTO with a null AwareDatetime."""
    account = Account(
        account_id=UUID("00000000-0000-0000-0000-000000000001"),
        primary_email="ghost@example.com",
        normalized_email="ghost@example.com",
        status=AccountStatus.DELETION_PENDING,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
        deletion_requested_at=None,
    )
    with pytest.raises(NotFoundError) as excinfo:
        _deletion_pending_response(account, datetime.now(timezone.utc))
    assert excinfo.value.error_code == "ACCOUNT_NOT_FOUND"
    assert excinfo.value.category == "NotFound"


async def test_delete_account_same_idempotency_key_replays_same_response(
    db_session: AsyncSession,
    valkey_client: Redis,
) -> None:
    """Idempotency-Key replay: a completed key returns the ORIGINAL success
    response; the account is not double-processed (still one deletion request
    row, FR-AUTH-030 AC-030.5)."""
    async with _client(db_session, valkey_client) as client:
        await _register(client, "idem@example.com")
        await _make_active(db_session, "idem@example.com")

        headers = {"Idempotency-Key": "delete-v1"}
        first = await client.post("/v1/auth/delete-account", headers=headers)
        second = await client.post("/v1/auth/delete-account", headers=headers)

    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json() == second.json()  # byte-identical replay
    row_count = await db_session.scalar(
        text(
            "SELECT count(*) FROM auth.account_deletion_requests WHERE account_id = :id"
        ),
        {"id": await _account_id(db_session, "idem@example.com")},
    )
    assert int(row_count or 0) == 1


async def test_delete_account_same_key_after_cancel_replays_original(
    db_session: AsyncSession,
    valkey_client: Redis,
) -> None:
    """Documented choice (per review I2): a COMPLETED key always replays the
    original success response — even after the deletion was cancelled — because
    the key identifies the original request (Stripe-style idempotency). The
    replay is a pure response replay: no new deletion row, account stays Active."""
    async with _client(db_session, valkey_client) as client:
        await _register(client, "idem-cancel@example.com")
        await _make_active(db_session, "idem-cancel@example.com")

        headers = {"Idempotency-Key": "delete-cancel-v1"}
        original = await client.post("/v1/auth/delete-account", headers=headers)
        assert original.status_code == 200
        cancelled = await client.post("/v1/auth/cancel-delete-account")
        assert cancelled.status_code == 200

        replay = await client.post("/v1/auth/delete-account", headers=headers)

    assert replay.status_code == 200
    assert replay.json() == original.json()  # original DeletionPending response
    row_count = await db_session.scalar(
        text(
            "SELECT count(*) FROM auth.account_deletion_requests WHERE account_id = :id"
        ),
        {"id": await _account_id(db_session, "idem-cancel@example.com")},
    )
    assert int(row_count or 0) == 1  # cancelled row, never a second one
    assert (
        await _account_status(
            db_session, await _account_id(db_session, "idem-cancel@example.com")
        )
        == "Active"
    )  # pure replay: the account itself is untouched


async def test_delete_account_in_flight_idempotency_key_409(
    db_session: AsyncSession,
    valkey_client: Redis,
) -> None:
    """A claimed-but-incomplete key (a concurrent in-flight request) maps to
    409 IDEMPOTENCY_KEY_CONFLICT (registered in error-codes.yaml)."""
    async with _client(db_session, valkey_client) as client:
        await _register(client, "inflight@example.com")
        account_id = await _make_active(db_session, "inflight@example.com")
        # Pre-claim the key directly through the store, simulating a concurrent
        # request that has claimed but not yet completed.
        store = PostgresIdempotencyRepository(db_session)
        claimed = await store.claim(f"delete-account:{account_id}:concurrent")
        assert claimed is True

        response = await client.post(
            "/v1/auth/delete-account", headers={"Idempotency-Key": "concurrent"}
        )

    assert response.status_code == 409
    body = response.json()
    assert body["category"] == "Conflict"
    assert body["errorCode"] == "IDEMPOTENCY_KEY_CONFLICT"
    assert body["messageKey"] == "auth.error.idempotencyKeyConflict"


async def test_delete_account_failed_attempt_releases_idempotency_key(
    db_session: AsyncSession,
    valkey_client: Redis,
) -> None:
    """A failed attempt (e.g. 401 RECENT_AUTHENTICATION_REQUIRED) releases the
    claim, so a later retry with the SAME key executes fresh instead of being
    permanently poisoned by the stale in-flight record."""
    async with _client(db_session, valkey_client) as client:
        await _register(client, "retry@example.com")
        await _make_active(db_session, "retry@example.com")
        await db_session.execute(
            text(
                "UPDATE auth.sessions SET last_strong_auth_at = :at "
                "WHERE status = 'Active'"
            ),
            {"at": datetime.now(timezone.utc) - timedelta(minutes=11)},
        )
        await db_session.flush()

        headers = {"Idempotency-Key": "retry-v1"}
        blocked = await client.post("/v1/auth/delete-account", headers=headers)
        assert blocked.status_code == 401  # RECENT_AUTHENTICATION_REQUIRED

        reauth = await client.post(
            "/v1/auth/reauthenticate", json={"password": VALID_PASSWORD}
        )
        assert reauth.status_code == 200

        retry = await client.post("/v1/auth/delete-account", headers=headers)

    assert retry.status_code == 200  # released claim -> fresh execution
    assert retry.json()["accountStatus"] == "DeletionPending"


async def _account_id(db_session: AsyncSession, email: str) -> UUID:
    value = await db_session.scalar(
        text("SELECT account_id FROM auth.accounts WHERE normalized_email = :email"),
        {"email": email.casefold()},
    )
    assert value is not None
    return value


# ---------------------------------------------------------------------------
# POST /v1/auth/cancel-delete-account
# ---------------------------------------------------------------------------


async def test_cancel_delete_restores_pre_deletion_status(
    db_session: AsyncSession,
    valkey_client: Redis,
) -> None:
    async with _client(db_session, valkey_client) as client:
        await _register(client, "cancel@example.com")
        account_id = await _make_active(db_session, "cancel@example.com")

        deleted = await client.post("/v1/auth/delete-account")
        assert deleted.status_code == 200
        assert deleted.json()["accountStatus"] == "DeletionPending"

        cancelled = await client.post("/v1/auth/cancel-delete-account")

    assert cancelled.status_code == 200
    body = cancelled.json()
    assert body["messageKey"] == "DELETION_CANCELLED"
    assert body["accountStatus"] == "Active"  # FR-AUTH-031: Active -> Active
    assert body["restoredAt"]
    assert await _account_status(db_session, account_id) == "Active"
    # The scheduled final deletion is cancelled.
    state = await db_session.scalar(
        text("SELECT state FROM auth.account_deletion_requests WHERE account_id = :id"),
        {"id": account_id},
    )
    assert state == "Cancelled"


async def test_cancel_delete_when_not_in_deletion_409(
    db_session: AsyncSession,
    valkey_client: Redis,
) -> None:
    async with _client(db_session, valkey_client) as client:
        await _register(client, "never@example.com")
        await _make_active(db_session, "never@example.com")

        response = await client.post("/v1/auth/cancel-delete-account")

    assert response.status_code == 409
    body = response.json()
    assert body["category"] == "Conflict"
    assert body["errorCode"] == "ACCOUNT_NOT_IN_DELETION"
    assert body["messageKey"] == "auth.error.accountNotInDeletion"


# ---------------------------------------------------------------------------
# GET /v1/auth/status
# ---------------------------------------------------------------------------


async def test_status_reports_grace_period_and_recovery_mode(
    db_session: AsyncSession,
    valkey_client: Redis,
) -> None:
    async with _client(db_session, valkey_client) as client:
        await _register(client, "grace@example.com")
        await _make_active(db_session, "grace@example.com")
        delete = await client.post("/v1/auth/delete-account")
        assert delete.status_code == 200
        requested = datetime.fromisoformat(delete.json()["deletionRequestedAt"])

        # BDD FR-AUTH-030: "进入第 5 天" -> 剩余 25 天。Fake-advance the clock by
        # editing the request timestamp so the remaining-days math is covered.
        await db_session.execute(
            text(
                "UPDATE auth.accounts SET deletion_requested_at = :at "
                "WHERE normalized_email = 'grace@example.com'"
            ),
            {"at": requested - timedelta(days=5)},
        )
        await db_session.flush()

        status = await client.get("/v1/auth/status")

    assert status.status_code == 200
    body = status.json()
    assert body["accountStatus"] == "DeletionPending"
    assert body["inAccountRecoveryMode"] is True
    assert body["deletionRequestedAt"]
    assert body["gracePeriodDaysRemaining"] == 25  # 30 - 5 elapsed days
    execute_after = datetime.fromisoformat(body["executeAfter"])
    assert (execute_after - datetime.fromisoformat(body["deletionRequestedAt"])) == (
        timedelta(days=30)
    )
    assert body["canCancelDeletion"] is True


async def test_status_for_non_deletion_account(
    db_session: AsyncSession,
    valkey_client: Redis,
) -> None:
    async with _client(db_session, valkey_client) as client:
        await _register(client, "plain@example.com")
        await _make_active(db_session, "plain@example.com")

        status = await client.get("/v1/auth/status")

    assert status.status_code == 200
    body = status.json()
    assert body["accountStatus"] == "Active"
    assert body["inAccountRecoveryMode"] is False
    assert body["deletionRequestedAt"] is None
    assert body["gracePeriodDaysRemaining"] is None
    assert body["executeAfter"] is None
    assert body["canCancelDeletion"] is False


# ---------------------------------------------------------------------------
# Recovery-mode guard (FR-AUTH-032)
# ---------------------------------------------------------------------------


async def test_recovery_guard_blocks_me_but_allows_deletion_endpoints(
    db_session: AsyncSession,
    valkey_client: Redis,
) -> None:
    async with _client(db_session, valkey_client) as client:
        await _register(client, "recovery@example.com")
        await _make_active(db_session, "recovery@example.com")
        delete = await client.post("/v1/auth/delete-account")
        assert delete.status_code == 200

        me = await client.get("/v1/auth/me")
        sess = await client.get("/v1/auth/session")
        status = await client.get("/v1/auth/status")
        cancel = await client.post("/v1/auth/cancel-delete-account")

    # Non-recovery endpoints are blocked with 403 (Permission).
    assert me.status_code == 403
    assert me.json()["category"] == "Permission"
    assert me.json()["errorCode"] == "ACCOUNT_IN_RECOVERY_MODE"
    assert sess.status_code == 403
    # Deletion endpoints stay reachable (FR-AUTH-032 allowed operations).
    assert status.status_code == 200
    assert cancel.status_code == 200
    assert cancel.json()["accountStatus"] == "Active"


async def test_recovery_guard_allows_login_and_reauth(
    db_session: AsyncSession,
    valkey_client: Redis,
) -> None:
    async with _client(db_session, valkey_client) as client:
        await _register(client, "recovery-login@example.com")
        await _make_active(db_session, "recovery-login@example.com")
        await client.post("/v1/auth/delete-account")

        login = await client.post(
            "/v1/auth/login",
            json={"email": "recovery-login@example.com", "password": VALID_PASSWORD},
        )
        reauth = await client.post(
            "/v1/auth/reauthenticate", json={"password": VALID_PASSWORD}
        )

    assert login.status_code == 200
    assert login.json()["recoveryModeRequired"] is True
    assert reauth.status_code == 200
