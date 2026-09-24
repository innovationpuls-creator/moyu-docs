from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

import pytest
from app_core.account.domain.account import AccountStatus
from app_core.account.ports.idempotency_repository import (
    IdempotencyRecord,
    IdempotencyState,
)
from app_core.common.exceptions import (
    IdempotencyConflictError,
    NotFoundError,
    PermissionDeniedError,
)
from app_core.permission.domain.workspace_membership import WorkspaceOperation
from app_core.workspace.application.use_cases import (
    CreateWorkspace,
    GetWorkspace,
    _request_fingerprint,
)
from app_core.workspace.domain.name import WorkspaceName

ACTOR_ID = UUID("10000000-0000-0000-0000-000000000001")
WORKSPACE_ID = UUID("20000000-0000-0000-0000-000000000002")
CREATED_AT = datetime(2026, 9, 24, 12, 0, tzinfo=UTC)


@dataclass(frozen=True)
class Workspace:
    workspace_id: UUID
    name: WorkspaceName
    created_by: UUID


class WorkspaceRepository:
    def __init__(self, workspace: Workspace | None = None) -> None:
        self.workspace = workspace
        self.saved: list[Workspace] = []

    async def save(self, workspace: Workspace) -> None:
        self.saved.append(workspace)
        self.workspace = workspace

    async def find_by_id(self, workspace_id: UUID) -> Workspace | None:
        if self.workspace and self.workspace.workspace_id == workspace_id:
            return self.workspace
        return None


class IdempotencyStore:
    def __init__(self) -> None:
        self.records: dict[str, tuple[str, IdempotencyRecord]] = {}

    async def claim(self, key: str, request_fingerprint: str) -> bool:
        if key in self.records:
            return False
        self.records[key] = (
            request_fingerprint,
            IdempotencyRecord(IdempotencyState.IN_PROGRESS),
        )
        return True

    async def get(self, key: str) -> IdempotencyRecord | None:
        record = self.records.get(key)
        return record[1] if record else None

    async def get_fingerprint(self, key: str) -> str | None:
        record = self.records.get(key)
        return record[0] if record else None

    async def complete(
        self, key: str, request_fingerprint: str, response: bytes
    ) -> None:
        self.records[key] = (
            request_fingerprint,
            IdempotencyRecord(IdempotencyState.COMPLETED, response),
        )


class AccountEligibility:
    def __init__(self, status: AccountStatus = AccountStatus.ACTIVE) -> None:
        self.status = status
        self.checked: list[UUID] = []

    async def workspace_creation_status(self, actor_id: UUID) -> AccountStatus | None:
        self.checked.append(actor_id)
        return self.status


class InitialOwnerGrant:
    def __init__(self) -> None:
        self.granted: list[tuple[UUID, UUID]] = []

    async def execute(self, workspace_id: UUID, actor_id: UUID) -> None:
        self.granted.append((workspace_id, actor_id))


class CurrentOwner:
    def __init__(self, owner: UUID | None = ACTOR_ID) -> None:
        self.owner = owner
        self.lookups: list[UUID] = []

    async def execute(self, workspace_id: UUID) -> UUID | None:
        self.lookups.append(workspace_id)
        return self.owner


class WorkspaceAccess:
    def __init__(self) -> None:
        self.authorized: list[tuple[UUID, WorkspaceOperation, UUID]] = []

    async def authorize(
        self,
        actor_id: UUID,
        operation: WorkspaceOperation,
        *,
        workspace_id: UUID,
        project_id: UUID | None = None,
    ) -> None:
        assert project_id is None
        self.authorized.append((actor_id, operation, workspace_id))


@pytest.mark.asyncio
async def test_create_workspace_persists_metadata_then_grants_creator_initial_owner():
    repository = WorkspaceRepository()
    owner_grant = InitialOwnerGrant()
    eligibility = AccountEligibility()
    idempotency = IdempotencyStore()
    use_case = CreateWorkspace(
        repository,
        owner_grant,
        eligibility,
        idempotency,
        id_factory=lambda: WORKSPACE_ID,
        now=lambda: CREATED_AT,
    )

    result = await use_case.execute(
        ACTOR_ID, "  系统设计  ", idempotency_key="create-1"
    )

    assert result.workspace.workspace_id == WORKSPACE_ID
    assert result.workspace.name == WorkspaceName("  系统设计  ")
    assert result.workspace.created_by == ACTOR_ID
    assert result.workspace.created_at == CREATED_AT
    assert result.owner_account_id == ACTOR_ID
    assert repository.saved == [result.workspace]
    assert eligibility.checked == [ACTOR_ID]
    assert owner_grant.granted == [(WORKSPACE_ID, ACTOR_ID)]
    assert not hasattr(repository, "commit")


@pytest.mark.asyncio
async def test_create_workspace_replays_persisted_result_for_same_key_and_request():
    repository = WorkspaceRepository()
    owner_grant = InitialOwnerGrant()
    eligibility = AccountEligibility()
    idempotency = IdempotencyStore()
    use_case = CreateWorkspace(
        repository,
        owner_grant,
        eligibility,
        idempotency,
        id_factory=lambda: WORKSPACE_ID,
        now=lambda: CREATED_AT,
    )

    first = await use_case.execute(ACTOR_ID, "Roadmap", idempotency_key="retry-1")
    second = await use_case.execute(ACTOR_ID, "Roadmap", idempotency_key="retry-1")

    assert second == first
    assert second.workspace.created_by == ACTOR_ID
    assert second.workspace.created_at == CREATED_AT
    assert len(repository.saved) == 1
    assert owner_grant.granted == [(WORKSPACE_ID, ACTOR_ID)]


@pytest.mark.asyncio
async def test_create_workspace_replays_when_claim_loses_to_completed_request():
    class CompletionRaceStore(IdempotencyStore):
        def __init__(self) -> None:
            super().__init__()
            self.first_read = True
            fingerprint = _request_fingerprint(ACTOR_ID, WorkspaceName("Roadmap"))
            payload = json.dumps(
                {
                    "workspace_id": str(WORKSPACE_ID),
                    "name": "Roadmap",
                    "created_by": str(ACTOR_ID),
                    "created_at": CREATED_AT.isoformat(),
                    "updated_at": CREATED_AT.isoformat(),
                    "lifecycle": "Active",
                    "owner_account_id": str(ACTOR_ID),
                }
            ).encode()
            self.records["race-key"] = (
                fingerprint,
                IdempotencyRecord(IdempotencyState.COMPLETED, payload),
            )

        async def get(self, key: str) -> IdempotencyRecord | None:
            if self.first_read:
                self.first_read = False
                return None
            return await super().get(key)

    repository = WorkspaceRepository()
    owner_grant = InitialOwnerGrant()
    use_case = CreateWorkspace(
        repository,
        owner_grant,
        AccountEligibility(),
        CompletionRaceStore(),
        id_factory=lambda: WORKSPACE_ID,
        now=lambda: CREATED_AT,
    )

    result = await use_case.execute(ACTOR_ID, "Roadmap", idempotency_key="race-key")

    assert result.workspace.workspace_id == WORKSPACE_ID
    assert result.workspace.created_at == CREATED_AT
    assert repository.saved == []
    assert owner_grant.granted == []


@pytest.mark.asyncio
async def test_create_workspace_rejects_control_character_name_with_typed_error():
    from app_core.common.exceptions import ValidationError

    repository = WorkspaceRepository()
    use_case = CreateWorkspace(
        repository,
        InitialOwnerGrant(),
        AccountEligibility(),
        IdempotencyStore(),
        id_factory=lambda: WORKSPACE_ID,
    )

    with pytest.raises(ValidationError) as error:
        await use_case.execute(ACTOR_ID, "bad\x00name", idempotency_key="create-ctrl")

    assert error.value.error_code == "WORKSPACE_NAME_INVALID"
    assert repository.saved == []


@pytest.mark.asyncio
async def test_create_workspace_conflicts_when_key_is_reused_for_different_name():
    repository = WorkspaceRepository()
    idempotency = IdempotencyStore()
    use_case = CreateWorkspace(
        repository,
        InitialOwnerGrant(),
        AccountEligibility(),
        idempotency,
        id_factory=lambda: WORKSPACE_ID,
    )

    await use_case.execute(ACTOR_ID, "Roadmap", idempotency_key="retry-2")

    with pytest.raises(IdempotencyConflictError) as error:
        await use_case.execute(ACTOR_ID, "Different name", idempotency_key="retry-2")

    assert error.value.error_code == "IDEMPOTENCY_KEY_CONFLICT"
    assert len(repository.saved) == 1


@pytest.mark.asyncio
async def test_create_workspace_conflicts_when_key_is_reused_by_different_actor():
    repository = WorkspaceRepository()
    idempotency = IdempotencyStore()
    use_case = CreateWorkspace(
        repository,
        InitialOwnerGrant(),
        AccountEligibility(),
        idempotency,
        id_factory=lambda: WORKSPACE_ID,
    )

    await use_case.execute(ACTOR_ID, "Roadmap", idempotency_key="retry-actor")
    other_actor = UUID("10000000-0000-0000-0000-000000000099")

    with pytest.raises(IdempotencyConflictError) as error:
        await use_case.execute(other_actor, "Roadmap", idempotency_key="retry-actor")

    assert error.value.error_code == "IDEMPOTENCY_KEY_CONFLICT"
    assert len(repository.saved) == 1


@pytest.mark.asyncio
async def test_create_workspace_denies_non_active_account_before_writes():

    repository = WorkspaceRepository()
    owner_grant = InitialOwnerGrant()
    eligibility = AccountEligibility(AccountStatus.PENDING_VERIFICATION)
    use_case = CreateWorkspace(
        repository,
        owner_grant,
        eligibility,
        IdempotencyStore(),
        id_factory=lambda: WORKSPACE_ID,
    )

    with pytest.raises(PermissionDeniedError, match="active Account"):
        await use_case.execute(ACTOR_ID, "Roadmap", idempotency_key="create-2")

    assert repository.saved == []
    assert owner_grant.granted == []


@pytest.mark.asyncio
async def test_create_workspace_grant_failure_does_not_return_success():
    class FailingGrant:
        async def execute(self, workspace_id: UUID, actor_id: UUID) -> None:
            raise RuntimeError("Permission unavailable")

    use_case = CreateWorkspace(
        WorkspaceRepository(),
        FailingGrant(),
        AccountEligibility(),
        IdempotencyStore(),
        id_factory=lambda: WORKSPACE_ID,
    )

    with pytest.raises(RuntimeError, match="Permission unavailable"):
        await use_case.execute(ACTOR_ID, "Roadmap", idempotency_key="create-3")


@pytest.mark.asyncio
async def test_get_workspace_authorizes_read_before_returning_metadata():

    workspace = Workspace(WORKSPACE_ID, WorkspaceName("Roadmap"), ACTOR_ID)
    repository = WorkspaceRepository(workspace)
    access = WorkspaceAccess()
    current_owner = CurrentOwner()
    use_case = GetWorkspace(repository, access, current_owner)

    result = await use_case.execute(ACTOR_ID, WORKSPACE_ID)

    assert access.authorized == [(ACTOR_ID, WorkspaceOperation.READ, WORKSPACE_ID)]
    assert result.workspace is workspace
    assert result.owner_account_id == ACTOR_ID
    assert current_owner.lookups == [WORKSPACE_ID]


@pytest.mark.asyncio
async def test_get_workspace_fails_closed_when_owner_projection_is_missing():
    from app_core.permission.domain.workspace_membership import (
        PermissionDependencyError,
    )

    workspace = Workspace(WORKSPACE_ID, WorkspaceName("Roadmap"), ACTOR_ID)
    use_case = GetWorkspace(
        WorkspaceRepository(workspace), WorkspaceAccess(), CurrentOwner(None)
    )

    with pytest.raises(PermissionDependencyError):
        await use_case.execute(ACTOR_ID, WORKSPACE_ID)


@pytest.mark.asyncio
async def test_get_workspace_missing_raises_typed_not_found():
    use_case = GetWorkspace(WorkspaceRepository(), WorkspaceAccess(), CurrentOwner())

    with pytest.raises(NotFoundError) as error:
        await use_case.execute(ACTOR_ID, WORKSPACE_ID)

    assert error.value.error_code == "WORKSPACE_NOT_FOUND"
    assert error.value.category == "NotFound"


@pytest.mark.asyncio
async def test_get_workspace_does_not_read_metadata_when_permission_denies():

    class DenyingAccess:
        async def authorize(
            self,
            actor_id: UUID,
            operation: WorkspaceOperation,
            *,
            workspace_id: UUID,
            project_id: UUID | None = None,
        ) -> None:
            raise PermissionError("denied")

    class UnreadableRepository:
        async def find_by_id(self, workspace_id: UUID) -> Workspace | None:
            raise AssertionError("metadata must not be fetched before authorization")

    use_case = GetWorkspace(UnreadableRepository(), DenyingAccess(), CurrentOwner())

    with pytest.raises(PermissionError, match="denied"):
        await use_case.execute(ACTOR_ID, WORKSPACE_ID)
