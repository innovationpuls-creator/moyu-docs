from __future__ import annotations

from typing import Any, cast
from uuid import UUID, uuid4

import pytest
from app_core.common.exceptions import PermissionDeniedError
from app_core.permission.domain.workspace_membership import WorkspaceOperation
from app_infra.postgres.permission_workspace_repository import (
    PostgresWorkspaceMembershipRepository,
)
from sqlalchemy.ext.asyncio import AsyncSession


class ScalarResult:
    def __init__(self, value: Any) -> None:
        self.value = value

    def scalar_one_or_none(self) -> Any:
        return self.value


class MappingResult:
    def __init__(self, row: dict[str, UUID]) -> None:
        self.row = row

    def mappings(self) -> MappingResult:
        return self

    def one_or_none(self) -> dict[str, UUID]:
        return self.row


class AccessSession:
    def __init__(self, results: list[Any]) -> None:
        self.results = iter(results)
        self.statements: list[tuple[str, dict[str, Any]]] = []

    async def execute(self, statement: Any, parameters: dict[str, Any]) -> Any:
        self.statements.append((str(statement), parameters))
        result = next(self.results)
        if isinstance(result, dict):
            return MappingResult(result)
        return ScalarResult(result)

    async def scalar(self, statement: Any, parameters: dict[str, Any]) -> Any:
        result = await self.execute(statement, parameters)
        return result.scalar_one_or_none()


def _repository(session: AccessSession) -> PostgresWorkspaceMembershipRepository:
    return PostgresWorkspaceMembershipRepository(cast(AsyncSession, session))


@pytest.mark.asyncio
async def test_workspace_member_can_read_and_owner_can_manage() -> None:
    actor_id, workspace_id = uuid4(), uuid4()
    owner = AccessSession(["Active", "Owner"])
    await _repository(owner).authorize(
        actor_id, WorkspaceOperation.MANAGE, workspace_id=workspace_id
    )
    member = AccessSession(["Active", "Member"])
    await _repository(member).authorize(
        actor_id, WorkspaceOperation.READ, workspace_id=workspace_id
    )
    with pytest.raises(PermissionDeniedError):
        await _repository(AccessSession(["Active", "Member"])).authorize(
            actor_id, WorkspaceOperation.MANAGE, workspace_id=workspace_id
        )


@pytest.mark.asyncio
async def test_non_member_and_inactive_workspace_fail_closed() -> None:
    actor_id, workspace_id = uuid4(), uuid4()
    with pytest.raises(PermissionDeniedError):
        await _repository(AccessSession(["Active", None])).authorize(
            actor_id, WorkspaceOperation.READ, workspace_id=workspace_id
        )
    with pytest.raises(PermissionDeniedError):
        await _repository(AccessSession(["Deleted"])).authorize(
            actor_id, WorkspaceOperation.READ, workspace_id=workspace_id
        )


@pytest.mark.asyncio
async def test_project_manage_is_inherited_only_from_workspace_owner() -> None:
    actor_id, workspace_id, project_id = uuid4(), uuid4(), uuid4()
    owner = AccessSession(["Active", {"workspace_id": workspace_id}, "Owner"])
    await _repository(owner).authorize(
        actor_id,
        WorkspaceOperation.MANAGE,
        workspace_id=workspace_id,
        project_id=project_id,
    )
    outsider = AccessSession(["Active", {"workspace_id": workspace_id}, None])
    with pytest.raises(PermissionDeniedError):
        await _repository(outsider).authorize(
            actor_id,
            WorkspaceOperation.MANAGE,
            workspace_id=workspace_id,
            project_id=project_id,
        )


@pytest.mark.asyncio
async def test_project_workspace_mismatch_and_unknown_operation_fail_closed() -> None:
    actor_id, workspace_id, project_id = uuid4(), uuid4(), uuid4()
    with pytest.raises(PermissionDeniedError):
        await _repository(
            AccessSession(["Active", {"workspace_id": uuid4()}])
        ).authorize(
            actor_id,
            WorkspaceOperation.READ,
            workspace_id=workspace_id,
            project_id=project_id,
        )
    with pytest.raises(PermissionDeniedError):
        await _repository(AccessSession([])).authorize(
            actor_id,
            cast(WorkspaceOperation, "UnknownOperation"),
            workspace_id=workspace_id,
        )


@pytest.mark.asyncio
async def test_workspace_create_authorization_fails_closed() -> None:
    with pytest.raises(PermissionDeniedError):
        await _repository(AccessSession([])).authorize(
            uuid4(), WorkspaceOperation.CREATE, workspace_id=uuid4()
        )
