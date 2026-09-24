from __future__ import annotations

from types import SimpleNamespace
from typing import Any, cast
from uuid import UUID

import pytest
from api.dependencies.auth import get_current_session
from api.dependencies.workspace_ownership import (
    PostgresWorkspaceOwnershipQuery,
    get_workspace_ownership,
)
from api.main import create_app
from api.middleware.recovery_mode_guard import get_recovery_guard
from httpx import ASGITransport, AsyncClient

ACCOUNT_ID = UUID("10000000-0000-0000-0000-000000000001")
WORKSPACE_ID = UUID("20000000-0000-0000-0000-000000000002")


class _Projection:
    def __init__(self, value: tuple[bool, str | None, UUID | None]) -> None:
        self.value = value
        self.calls: list[UUID] = []

    async def sole_owned_workspace(
        self, account_id: UUID
    ) -> tuple[bool, str | None, UUID | None]:
        self.calls.append(account_id)
        return self.value


@pytest.mark.asyncio
async def test_workspace_ownership_route_maps_projection() -> None:
    projection = _Projection((True, "Research", WORKSPACE_ID))
    app = create_app(debug=True)
    app.dependency_overrides[get_current_session] = lambda: SimpleNamespace(
        account_id=ACCOUNT_ID
    )
    app.dependency_overrides[get_recovery_guard] = lambda: None
    app.dependency_overrides[get_workspace_ownership] = lambda: projection

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get("/v1/auth/my-workspace-ownership")

    assert response.status_code == 200
    assert response.json() == {
        "hasSoleWorkspaceOwnership": True,
        "workspaceId": str(WORKSPACE_ID),
    }
    assert projection.calls == [ACCOUNT_ID]


@pytest.mark.asyncio
async def test_workspace_ownership_route_nulls_workspace_for_non_sole() -> None:
    projection = _Projection((False, None, None))
    app = create_app(debug=True)
    app.dependency_overrides[get_current_session] = lambda: SimpleNamespace(
        account_id=ACCOUNT_ID
    )
    app.dependency_overrides[get_recovery_guard] = lambda: None
    app.dependency_overrides[get_workspace_ownership] = lambda: projection

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get("/v1/auth/my-workspace-ownership")

    assert response.status_code == 200
    assert response.json() == {
        "hasSoleWorkspaceOwnership": False,
        "workspaceId": None,
    }


@pytest.mark.asyncio
async def test_workspace_ownership_route_requires_authentication() -> None:
    app = create_app(debug=True)
    app.dependency_overrides[get_recovery_guard] = lambda: None

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get("/v1/auth/my-workspace-ownership")

    assert response.status_code == 401
    assert response.json()["category"] == "Authentication"


@pytest.mark.asyncio
async def test_workspace_ownership_dependency_delegates_to_membership_repository() -> (
    None
):
    class _Membership:
        async def sole_owned_workspace(self, account_id: UUID):
            return True, "Research", WORKSPACE_ID

    query = PostgresWorkspaceOwnershipQuery.__new__(PostgresWorkspaceOwnershipQuery)
    query._membership_repository = cast(Any, _Membership())
    assert await query.sole_owned_workspace(ACCOUNT_ID) == (
        True,
        "Research",
        WORKSPACE_ID,
    )
    assert await query.has_sole_workspace_ownership(ACCOUNT_ID) == (True, "Research")
