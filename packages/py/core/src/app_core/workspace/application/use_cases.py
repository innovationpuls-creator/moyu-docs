from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from uuid import UUID, uuid4

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
from app_core.permission.application.workspace_ownership import (
    GetCurrentWorkspaceOwner,
    GrantInitialWorkspaceOwner,
)
from app_core.permission.domain.workspace_membership import (
    PermissionDependencyError,
    WorkspaceOperation,
)
from app_core.permission.ports.workspace_access import WorkspaceAccessPort
from app_core.workspace.application.names import validated_workspace_name
from app_core.workspace.domain.lifecycle import WorkspaceLifecycle
from app_core.workspace.domain.name import WorkspaceName
from app_core.workspace.ports.account_workspace_eligibility import (
    AccountWorkspaceEligibilityPort,
)
from app_core.workspace.ports.events import LifecycleEvent, LifecycleEventPublisher
from app_core.workspace.ports.idempotency import WorkspaceIdempotencyPort
from app_core.workspace.ports.workspace_repository import WorkspaceRepository


@dataclass(frozen=True)
class Workspace:
    """Workspace identity, display metadata, and trusted creator identity."""

    workspace_id: UUID
    name: WorkspaceName
    created_by: UUID
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    lifecycle: WorkspaceLifecycle = WorkspaceLifecycle.ACTIVE


@dataclass(frozen=True)
class CreateWorkspaceResult:
    workspace: Workspace
    owner_account_id: UUID


@dataclass(frozen=True)
class GetWorkspaceResult:
    workspace: Workspace
    owner_account_id: UUID


class CreateWorkspace:
    def __init__(
        self,
        workspaces: WorkspaceRepository,
        initial_owner: GrantInitialWorkspaceOwner,
        account_eligibility: AccountWorkspaceEligibilityPort,
        idempotency: WorkspaceIdempotencyPort,
        events: LifecycleEventPublisher | None = None,
        *,
        id_factory: Callable[[], UUID] = uuid4,
        now: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._workspaces = workspaces
        self._initial_owner = initial_owner
        self._account_eligibility = account_eligibility
        self._idempotency = idempotency
        self._events = events
        self._id_factory = id_factory
        self._now = now

    async def execute(
        self, actor_id: UUID, name: str, *, idempotency_key: str
    ) -> CreateWorkspaceResult:
        account_status = await self._account_eligibility.workspace_creation_status(
            actor_id
        )
        if account_status is not AccountStatus.ACTIVE:
            raise PermissionDeniedError(
                "Workspace creation requires an active Account",
                "WORKSPACE_CREATION_REQUIRES_ACTIVE_ACCOUNT",
            )

        workspace_name = validated_workspace_name(name)
        request_fingerprint = _request_fingerprint(actor_id, workspace_name)
        prior = await self._idempotency.get(idempotency_key)
        if isinstance(prior, IdempotencyRecord):
            stored_fingerprint = await self._idempotency.get_fingerprint(
                idempotency_key
            )
            if stored_fingerprint != request_fingerprint:
                raise IdempotencyConflictError("IDEMPOTENCY_KEY_CONFLICT")
            if prior.state is IdempotencyState.COMPLETED and prior.response:
                return _result_from_payload(prior.response)
            if prior.state is IdempotencyState.IN_PROGRESS:
                raise IdempotencyConflictError("IDEMPOTENCY_KEY_CONFLICT")
        if not await self._idempotency.claim(idempotency_key, request_fingerprint):
            stored_fingerprint = await self._idempotency.get_fingerprint(
                idempotency_key
            )
            if stored_fingerprint != request_fingerprint:
                raise IdempotencyConflictError("IDEMPOTENCY_KEY_CONFLICT")
            prior = await self._idempotency.get(idempotency_key)
            if (
                isinstance(prior, IdempotencyRecord)
                and prior.state is IdempotencyState.COMPLETED
                and prior.response
            ):
                return _result_from_payload(prior.response)
            raise IdempotencyConflictError("IDEMPOTENCY_KEY_CONFLICT")

        created_at = self._now()
        workspace = Workspace(
            self._id_factory(),
            workspace_name,
            actor_id,
            created_at,
            created_at,
            WorkspaceLifecycle.ACTIVE,
        )
        await self._workspaces.save(workspace)
        await self._initial_owner.execute(workspace.workspace_id, actor_id)
        if self._events is not None:
            await self._events.publish(
                LifecycleEvent.create(
                    "WorkspaceCreated",
                    "event.workspace.created.v1",
                    workspace.workspace_id,
                    {
                        "workspaceId": str(workspace.workspace_id),
                        "actorAccountId": str(actor_id),
                        "name": workspace.name.display,
                    },
                    occurred_at=workspace.created_at,
                )
            )
        result = CreateWorkspaceResult(workspace, actor_id)
        await self._idempotency.complete(
            idempotency_key, request_fingerprint, _result_payload(result)
        )
        return result


class GetWorkspace:
    def __init__(
        self,
        workspaces: WorkspaceRepository,
        access: WorkspaceAccessPort,
        current_owner: GetCurrentWorkspaceOwner,
    ) -> None:
        self._workspaces = workspaces
        self._access = access
        self._current_owner = current_owner

    async def execute(self, actor_id: UUID, workspace_id: UUID) -> GetWorkspaceResult:
        await self._access.authorize(
            actor_id, WorkspaceOperation.READ, workspace_id=workspace_id
        )
        workspace = await self._workspaces.find_by_id(workspace_id)
        if workspace is None:
            raise NotFoundError(
                f"Workspace {workspace_id} was not found", "WORKSPACE_NOT_FOUND"
            )
        owner_account_id = await self._current_owner.execute(workspace_id)
        if owner_account_id is None:
            raise PermissionDependencyError(
                "Non-Deleted Workspace has no current Owner"
            )
        return GetWorkspaceResult(workspace, owner_account_id)


def _request_fingerprint(actor_id: UUID, name: WorkspaceName) -> str:
    canonical_request = json.dumps(
        {"actor_id": str(actor_id), "name": name.display},
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )
    return hashlib.sha256(canonical_request.encode("utf-8")).hexdigest()


def _result_payload(result: CreateWorkspaceResult) -> bytes:
    return json.dumps(
        {
            "workspace_id": str(result.workspace.workspace_id),
            "name": result.workspace.name.display,
            "created_by": str(result.workspace.created_by),
            "created_at": result.workspace.created_at.isoformat(),
            "updated_at": result.workspace.updated_at.isoformat(),
            "lifecycle": result.workspace.lifecycle.value,
            "owner_account_id": str(result.owner_account_id),
        },
        sort_keys=True,
    ).encode()


def _result_from_payload(payload: bytes) -> CreateWorkspaceResult:
    stored = json.loads(payload.decode())
    return CreateWorkspaceResult(
        Workspace(
            UUID(stored["workspace_id"]),
            WorkspaceName(stored["name"]),
            UUID(stored["created_by"]),
            datetime.fromisoformat(stored["created_at"]),
            datetime.fromisoformat(stored["updated_at"]),
            WorkspaceLifecycle(stored["lifecycle"]),
        ),
        UUID(stored["owner_account_id"]),
    )
