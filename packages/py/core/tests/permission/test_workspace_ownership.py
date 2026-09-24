from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from uuid import UUID, uuid4

import pytest
from app_core.common.exceptions import PermissionDeniedError
from app_core.permission.application.workspace_ownership import (
    GetCurrentWorkspaceOwner,
    GrantInitialWorkspaceOwner,
    HasSoleWorkspaceOwnership,
    TransferWorkspaceOwner,
)
from app_core.permission.domain.workspace_membership import (
    PermissionDependencyError,
    WorkspaceMembership,
    WorkspaceMembershipKind,
    WorkspaceOperation,
    WorkspaceOwnerTransferResult,
    can_manage_project,
)
from app_core.permission.ports.workspace_membership_repository import (
    AccountStatusProjection,
)


@dataclass(frozen=True)
class AccountProjection:
    account_id: UUID
    status: str


def test_account_projection_exposes_only_transfer_status():
    projection: AccountStatusProjection = AccountProjection(uuid4(), "Active")
    assert projection.status == "Active"


class Memberships:
    def __init__(
        self,
        transfer_result=None,
        sole_result=(False, None),
        current_owner=None,
    ):
        self.transfer_result = transfer_result
        self.sole_result = sole_result
        self.current_owner = current_owner
        self.grants = []
        self.transfer_calls = []

    async def grant_initial_owner(self, workspace_id: UUID, account_id: UUID) -> None:
        self.grants.append((workspace_id, account_id))

    async def transfer_owner_idempotently(
        self,
        actor_id: UUID,
        workspace_id: UUID,
        new_owner_id: UUID,
        idempotency_key: str,
    ) -> WorkspaceOwnerTransferResult:
        self.transfer_calls.append(
            (actor_id, workspace_id, new_owner_id, idempotency_key)
        )
        if self.transfer_result is None:
            raise PermissionDeniedError("Atomic transfer was not explicitly permitted.")
        return self.transfer_result

    async def has_sole_ownership(self, account_id: UUID) -> tuple[bool, str | None]:
        return self.sole_result

    async def get_current_workspace_owner(self, workspace_id: UUID) -> UUID | None:
        return self.current_owner


class FailClosedAccess:
    async def authorize(
        self,
        actor_id: UUID,
        operation: WorkspaceOperation,
        *,
        workspace_id: UUID,
        project_id: UUID | None = None,
    ) -> None:
        raise PermissionDeniedError("Permission authorization not explicitly allowed.")


class AllowAccess(FailClosedAccess):
    async def authorize(
        self,
        actor_id: UUID,
        operation: WorkspaceOperation,
        *,
        workspace_id: UUID,
        project_id: UUID | None = None,
    ) -> None:
        return None


class BrokenOwnership:
    async def has_sole_ownership(self, account_id):
        raise PermissionDependencyError("PERMISSION_QUERY_FAILED")


class BrokenCurrentOwner:
    async def get_current_workspace_owner(self, workspace_id: UUID) -> UUID | None:
        raise PermissionDependencyError("PERMISSION_QUERY_FAILED")


def test_membership_kind_values_are_exact_and_only_defined_values_are_accepted():
    assert WorkspaceMembershipKind.OWNER.value == "Owner"
    assert WorkspaceMembershipKind.MEMBER.value == "Member"
    with pytest.raises(ValueError):
        WorkspaceMembershipKind("Admin")


def test_owner_inherits_project_manage_only_within_its_workspace():
    owner = WorkspaceMembership(uuid4(), uuid4(), WorkspaceMembershipKind.OWNER)
    member = WorkspaceMembership(
        owner.workspace_id, uuid4(), WorkspaceMembershipKind.MEMBER
    )
    assert can_manage_project(owner, owner.workspace_id)
    assert not can_manage_project(owner, uuid4())
    assert not can_manage_project(member, member.workspace_id)


def test_transfer_result_keeps_old_owner_as_member_without_project_role_mutation():
    result = WorkspaceOwnerTransferResult(
        workspace_id=uuid4(),
        previous_owner_account_id=uuid4(),
        new_owner_account_id=uuid4(),
        transferred_at=datetime.now(UTC),
    )
    assert result.previous_owner_remains_member is True
    assert result.independent_project_owner_rows_changed is False


@pytest.mark.asyncio
async def test_initial_owner_grant_delegates_to_membership_repository():
    workspace_id, actor_id = uuid4(), uuid4()
    memberships = Memberships()
    await GrantInitialWorkspaceOwner(memberships).execute(workspace_id, actor_id)
    assert memberships.grants == [(workspace_id, actor_id)]


@pytest.mark.asyncio
async def test_transfer_is_one_atomic_repository_call_with_actor_and_idempotency():
    actor_id, workspace_id, target_id = uuid4(), uuid4(), uuid4()
    result = WorkspaceOwnerTransferResult(
        workspace_id, actor_id, target_id, datetime.now(UTC)
    )
    memberships = Memberships(transfer_result=result)
    actual = await TransferWorkspaceOwner(memberships).execute(
        actor_id, workspace_id, target_id, "transfer-1"
    )
    assert actual is result
    assert memberships.transfer_calls == [
        (actor_id, workspace_id, target_id, "transfer-1")
    ]


@pytest.mark.asyncio
async def test_transfer_repository_fails_closed_without_explicit_atomic_allow():
    memberships = Memberships()
    with pytest.raises(PermissionDeniedError):
        await TransferWorkspaceOwner(memberships).execute(
            uuid4(), uuid4(), uuid4(), "transfer-1"
        )
    assert memberships.transfer_calls


@pytest.mark.asyncio
async def test_access_port_fake_fails_closed_by_default():
    with pytest.raises(PermissionDeniedError):
        await FailClosedAccess().authorize(
            uuid4(), WorkspaceOperation.MANAGE, workspace_id=uuid4()
        )
    await AllowAccess().authorize(
        uuid4(), WorkspaceOperation.MANAGE, workspace_id=uuid4()
    )


@pytest.mark.asyncio
async def test_current_workspace_owner_is_read_from_permission_repository():
    workspace_id, owner_id = uuid4(), uuid4()
    assert (
        await GetCurrentWorkspaceOwner(Memberships(current_owner=owner_id)).execute(
            workspace_id
        )
        == owner_id
    )


@pytest.mark.asyncio
async def test_current_workspace_owner_returns_none_when_membership_is_absent():
    assert await GetCurrentWorkspaceOwner(Memberships()).execute(uuid4()) is None


@pytest.mark.asyncio
async def test_current_workspace_owner_propagates_dependency_failure():
    with pytest.raises(PermissionDependencyError):
        await GetCurrentWorkspaceOwner(BrokenCurrentOwner()).execute(uuid4())


@pytest.mark.asyncio
async def test_sole_ownership_returns_repository_answer():
    memberships = Memberships(sole_result=(True, "workspace"))
    assert await HasSoleWorkspaceOwnership(memberships).execute(uuid4()) == (
        True,
        "workspace",
    )


@pytest.mark.asyncio
async def test_sole_ownership_propagates_typed_dependency_failure():
    with pytest.raises(PermissionDependencyError) as error:
        await HasSoleWorkspaceOwnership(BrokenOwnership()).execute(uuid4())
    assert error.value.category == "Unavailable"
    assert error.value.error_code == "WORKSPACE_AUTHORIZATION_UNAVAILABLE"


def test_operation_vocabulary_is_string_enum():
    assert issubclass(WorkspaceOperation, StrEnum)
