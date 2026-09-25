from __future__ import annotations

import base64
import os
from types import SimpleNamespace
from uuid import uuid4

import pytest
from api.config import settings
from api.dependencies.auth import get_current_session, get_db_session
from api.dependencies.permission import get_permission_administration
from api.routes.permissions import router as permissions_router
from app_core.permission.application.administration import PermissionAdministration
from app_core.permission.domain.access_control import (
    EffectivePermission,
    PermissionCapability,
    PermissionRole,
)
from app_core.permission.domain.collaboration import InvitationAcceptanceExpired
from fastapi import Depends, FastAPI
from httpx import ASGITransport, AsyncClient


class ExpiredInvitationRepository:
    def __init__(self) -> None:
        self.expired_state_recorded = False

    async def accept_workspace_invitation(self, actor_id, token_hash):
        self.expired_state_recorded = True
        return InvitationAcceptanceExpired()


class ResourceCapabilitiesRepository:
    async def get_resource_capabilities(self, actor_id, resource_id):
        return EffectivePermission(
            PermissionRole.EDIT,
            frozenset(
                {
                    PermissionCapability.READ,
                    PermissionCapability.EDIT,
                    PermissionCapability.COMMENT,
                    PermissionCapability.RESOLVE_COMMENT,
                    PermissionCapability.REOPEN_COMMENT,
                }
            ),
        )


def test_permission_dependency_loads_fixture_key_and_requires_configuration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    key = os.urandom(32)
    monkeypatch.setattr(
        settings,
        "invitation_idempotency_encryption_key",
        base64.b64encode(key).decode(),
    )

    use_case = get_permission_administration(SimpleNamespace())

    assert use_case._repository._idempotency_encryption_key == key
    monkeypatch.setattr(settings, "invitation_idempotency_encryption_key", None)
    with pytest.raises(RuntimeError, match="is required"):
        get_permission_administration(SimpleNamespace())


@pytest.mark.asyncio
async def test_expired_invitation_returns_conflict_and_commits_recorded_state() -> None:
    actor_id = uuid4()
    repository = ExpiredInvitationRepository()
    transaction = SimpleNamespace(committed=False, rolled_back=False)
    app = FastAPI()
    app.include_router(permissions_router, prefix="/v1")

    async def current_session():
        return SimpleNamespace(account_id=actor_id)

    async def database_session():
        try:
            yield transaction
        except Exception:
            transaction.rolled_back = True
            raise
        else:
            transaction.committed = True

    async def permission_administration(
        session=Depends(get_db_session),
    ):
        assert session is transaction
        return PermissionAdministration(repository)

    app.dependency_overrides[get_current_session] = current_session
    app.dependency_overrides[get_db_session] = database_session
    app.dependency_overrides[get_permission_administration] = permission_administration

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post(
            "/v1/invitations/accept",
            json={"token": "expired-invitation-token-0123456789"},
        )

    assert response.status_code == 409, response.text
    assert response.json()["errorCode"] == "INVITATION_EXPIRED"
    assert response.json()["category"] == "Conflict"
    assert transaction.committed is True
    assert transaction.rolled_back is False
    assert repository.expired_state_recorded is True


@pytest.mark.asyncio
async def test_resource_capabilities_uses_the_authenticated_actor() -> None:
    actor_id, resource_id = uuid4(), uuid4()
    repository = ResourceCapabilitiesRepository()
    app = FastAPI()
    app.include_router(permissions_router, prefix="/v1")

    async def current_session():
        return SimpleNamespace(account_id=actor_id)

    async def permission_administration():
        return PermissionAdministration(repository)

    app.dependency_overrides[get_current_session] = current_session
    app.dependency_overrides[get_permission_administration] = permission_administration

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get(f"/v1/resources/{resource_id}/capabilities")

    assert response.status_code == 200, response.text
    assert response.json() == {
        "resourceId": str(resource_id),
        "canRead": True,
        "canUpdate": True,
        "canComment": True,
        "canManage": False,
        "canResolveCommentThread": True,
        "canReopenCommentThread": True,
    }
