"""Auth deletion routes (plan Task 24): delete-account / cancel-delete-account /
status.

Boundary discipline (doc 27 §16/§17, doc 28 §48): request/response bodies are
the GENERATED app-contracts DTOs. Per the canonical contract
(contracts/commands/auth/request-account-deletion.schema.json et al.) both
deletion commands are NO-BODY commands (registry requestBody: none) — the actor
is resolved from the dom_session cookie.

- POST /v1/auth/delete-account: RequestAccountDeletion (FR-AUTH-029/030);
  RECENT_AUTHENTICATION_REQUIRED -> 401, ACCOUNT_DELETION_SOLE_OWNER -> 409
  with the exact BDD message, success -> 200 DeletionPending + grace fields.
- POST /v1/auth/cancel-delete-account: CancelAccountDeletion (FR-AUTH-031);
  Active/PendingVerification restore; ACCOUNT_NOT_IN_DELETION -> 409.
- GET /v1/auth/status: GetAccountStatus (FR-AUTH-030 AC-030.2 / FR-AUTH-032:
  deletion state + grace window; fields null unless DeletionPending).
"""

from __future__ import annotations

from datetime import datetime, timedelta

from app_contracts.commands.auth.cancel_account_deletion import (
    CancelAccountDeletionResponse,
)
from app_contracts.commands.auth.request_account_deletion import (
    RequestAccountDeletionResponse,
)
from app_contracts.ids import ids
from app_contracts.queries.auth.get_account_status import GetAccountStatusResponse
from app_core.account.application.deletion import (
    CancelAccountDeletion,
    RequestAccountDeletion,
)
from app_core.account.domain.account import AccountStatus
from app_core.account.ports.workspace_ownership_query_port import (
    WorkspaceOwnershipQueryPort,
)
from app_core.common.exceptions import ConflictError
from app_core.session.domain.session import Session
from app_infra.postgres.account_repository import PostgresAccountRepository
from app_infra.postgres.audit_repository import PostgresAuditRepository
from app_infra.postgres.deletion_repository import PostgresDeletionRepository
from app_infra.postgres.session_repository import PostgresSessionRepository
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from api.dependencies.auth import (
    DELETION_CANCELLED_KEY,
    DELETION_REQUESTED_KEY,
    get_current_session,
    get_db_session,
    utc_now,
)
from api.dependencies.workspace_ownership import get_workspace_ownership

router = APIRouter()

# Fixed product rule (FR-AUTH-030 / doc 16 §40): 30-day grace period.
GRACE_PERIOD_DAYS = 30


def _grace_period_days_remaining(now: datetime, requested_at: datetime) -> int:
    """BDD FR-AUTH-030: “第 5 天” -> 剩余 25 天 (30 - elapsed days)."""
    elapsed = (now - requested_at).days
    return max(0, GRACE_PERIOD_DAYS - elapsed)


def _execute_after(requested_at: datetime) -> datetime:
    return requested_at + timedelta(days=GRACE_PERIOD_DAYS)


@router.post("/delete-account", response_model=RequestAccountDeletionResponse)
async def delete_account(
    current: Session = Depends(get_current_session),
    session: AsyncSession = Depends(get_db_session),
    ownership: WorkspaceOwnershipQueryPort = Depends(get_workspace_ownership),
) -> RequestAccountDeletionResponse:
    use_case = RequestAccountDeletion(
        PostgresAccountRepository(session),
        PostgresSessionRepository(session),
        ownership,
        PostgresAuditRepository(session),
        PostgresDeletionRepository(session),
        now=utc_now,
    )
    await use_case.execute(current.account_id, current.session_id)
    record = await PostgresAccountRepository(session).find_by_account_id(
        current.account_id
    )
    if record is None:
        raise ConflictError("ACCOUNT_NOT_FOUND", "ACCOUNT_NOT_FOUND")
    account = record.account
    assert account.deletion_requested_at is not None
    now = utc_now()
    return RequestAccountDeletionResponse(
        messageKey=DELETION_REQUESTED_KEY,
        accountStatus=ids.AccountStatusValue(account.status.value),
        deletionRequestedAt=account.deletion_requested_at,
        gracePeriodDaysRemaining=_grace_period_days_remaining(
            now, account.deletion_requested_at
        ),
        executeAfter=_execute_after(account.deletion_requested_at),
    )


@router.post("/cancel-delete-account", response_model=CancelAccountDeletionResponse)
async def cancel_delete_account(
    current: Session = Depends(get_current_session),
    session: AsyncSession = Depends(get_db_session),
) -> CancelAccountDeletionResponse:
    accounts = PostgresAccountRepository(session)
    record = await accounts.find_by_account_id(current.account_id)
    if record is None:
        raise ConflictError("ACCOUNT_NOT_IN_DELETION", "ACCOUNT_NOT_IN_DELETION")
    if record.account.status is not AccountStatus.DELETION_PENDING:
        raise ConflictError("ACCOUNT_NOT_IN_DELETION", "ACCOUNT_NOT_IN_DELETION")
    now = utc_now()
    use_case = CancelAccountDeletion(
        accounts,
        PostgresAuditRepository(session),
        PostgresDeletionRepository(session),
        now=utc_now,
    )
    await use_case.execute(current.account_id)
    restored = await accounts.find_by_account_id(current.account_id)
    if restored is None:
        raise ConflictError("ACCOUNT_NOT_IN_DELETION", "ACCOUNT_NOT_IN_DELETION")
    return CancelAccountDeletionResponse(
        messageKey=DELETION_CANCELLED_KEY,
        accountStatus=ids.AccountStatusValue(restored.account.status.value),
        restoredAt=now,
    )


@router.get("/status", response_model=GetAccountStatusResponse)
async def account_status(
    current: Session = Depends(get_current_session),
    session: AsyncSession = Depends(get_db_session),
) -> GetAccountStatusResponse:
    record = await PostgresAccountRepository(session).find_by_account_id(
        current.account_id
    )
    if record is None:
        raise ConflictError("ACCOUNT_NOT_FOUND", "ACCOUNT_NOT_FOUND")
    account = record.account
    pending = account.status is AccountStatus.DELETION_PENDING
    now = utc_now()
    requested_at: datetime | None = account.deletion_requested_at
    return GetAccountStatusResponse(
        accountStatus=ids.AccountStatusValue(account.status.value),
        inAccountRecoveryMode=account.is_in_recovery_mode(),
        deletionRequestedAt=requested_at if pending else None,
        gracePeriodDaysRemaining=(
            _grace_period_days_remaining(now, requested_at)
            if pending and requested_at is not None
            else None
        ),
        executeAfter=(
            _execute_after(requested_at)
            if pending and requested_at is not None
            else None
        ),
        canCancelDeletion=pending,
    )
