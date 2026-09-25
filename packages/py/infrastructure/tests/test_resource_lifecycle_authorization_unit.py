from __future__ import annotations

from uuid import uuid4

import pytest
from app_core.permission.domain.access_control import PermissionCapability
from app_infra.postgres.permission_administration_repository import (
    PostgresPermissionAdministrationRepository,
)
from app_infra.postgres.resource_ownership_repository import (
    PostgresResourceOwnershipRepository,
)


class _Result:
    def __init__(self, row: dict[str, object]) -> None:
        self._row = row

    def mappings(self) -> _Result:
        return self

    def one_or_none(self) -> dict[str, object]:
        return self._row


class _Session:
    def __init__(self, row: dict[str, object]) -> None:
        self.row = row
        self.statement = ""

    async def execute(self, statement, _parameters) -> _Result:
        self.statement = str(statement)
        return _Result(self.row)


def _permission_row(resource_lifecycle: str) -> dict[str, object]:
    return {
        "workspace_status": "Active",
        "project_lifecycle": "Active",
        "resource_lifecycle": resource_lifecycle,
        "membership_kind": "Owner",
        "project_role": None,
        "resource_role": None,
    }


def _ownership_row(resource_lifecycle: str) -> dict[str, object]:
    return {
        "workspace_id": uuid4(),
        "project_id": uuid4(),
        "project_lifecycle": "Active",
        "resource_lifecycle": resource_lifecycle,
        "workspace_status": "Active",
        "membership_kind": "Owner",
        "project_role": None,
        "resource_role": None,
    }


@pytest.mark.asyncio
@pytest.mark.parametrize("lifecycle", ["Trashed", "Purging", "Purged", "Deleted"])
async def test_capabilities_are_absent_for_non_active_resource(
    lifecycle: str,
) -> None:
    session = _Session(_permission_row(lifecycle))
    repository = PostgresPermissionAdministrationRepository(session, b"k" * 32)

    permission = await repository.get_resource_capabilities(uuid4(), uuid4())

    assert "r.lifecycle AS resource_lifecycle" in session.statement
    assert permission is None


@pytest.mark.asyncio
@pytest.mark.parametrize("lifecycle", ["Trashed", "Purging", "Purged", "Deleted"])
@pytest.mark.parametrize("operation", ["resource.read", "resource.update"])
async def test_resource_ownership_authorization_denies_non_active_resource(
    lifecycle: str, operation: str
) -> None:
    session = _Session(_ownership_row(lifecycle))
    repository = PostgresResourceOwnershipRepository(session)

    allowed = await repository.authorize(uuid4(), uuid4(), operation)

    assert "r.lifecycle AS resource_lifecycle" in session.statement
    assert not allowed


@pytest.mark.asyncio
async def test_active_resource_remains_authorized() -> None:
    session = _Session(_permission_row("Active"))
    repository = PostgresPermissionAdministrationRepository(session, b"k" * 32)

    permission = await repository.get_resource_capabilities(uuid4(), uuid4())

    assert permission is not None
    assert permission.allows(PermissionCapability.EDIT)
