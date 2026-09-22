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

from api.dependencies.auth import get_db_session, get_valkey
from api.dependencies.workspace_ownership import (
    WorkspaceOwnershipQueryPort,
    get_workspace_ownership,
)
from api.main import create_app
from app_infra.postgres.account_repository import PostgresAccountRepository
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
