from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from app_core.permission.application.administration import PermissionAdministration
from app_core.permission.domain.collaboration import (
    CreatedWorkspaceInvitation,
    InvitationAcceptanceExpired,
    WorkspaceInvitationView,
)


class InvitationRepository:
    def __init__(self) -> None:
        self.create_call = None
        self.accept_result = None

    async def create_workspace_invitation(
        self,
        actor_id,
        workspace_id,
        target_email,
        token_hash,
        invitation_url,
        expires_at,
        expires_in_days,
        idempotency_key,
    ):
        self.create_call = (
            actor_id,
            workspace_id,
            target_email,
            token_hash,
            invitation_url,
            expires_at,
            expires_in_days,
            idempotency_key,
        )
        return CreatedWorkspaceInvitation(
            WorkspaceInvitationView(
                uuid4(),
                workspace_id,
                target_email,
                None,
                "Member",
                "Pending",
                expires_at,
                actor_id,
                datetime.now(UTC),
            ),
            invitation_url,
        )

    async def accept_workspace_invitation(self, actor_id, token_hash):
        self.accept_call = (actor_id, token_hash)
        return self.accept_result


@pytest.mark.asyncio
async def test_invitation_creation_hashes_token_and_returns_relative_url() -> None:
    repository = InvitationRepository()
    actor_id, workspace_id = uuid4(), uuid4()
    use_case = PermissionAdministration(
        repository,
        now=lambda: datetime(2026, 9, 25, tzinfo=UTC),
        token_factory=lambda _: "opaque/token",
    )

    created = await use_case.create_workspace_invitation(
        actor_id, workspace_id, "  User@Example.Test ", "request-1", 5
    )

    assert created.invitation_url == "/invite/accept?token=opaque%2Ftoken"
    assert repository.create_call is not None
    assert repository.create_call[2] == "user@example.test"
    assert repository.create_call[3] == hashlib.sha256(b"opaque/token").hexdigest()
    assert repository.create_call[4] == created.invitation_url
    assert repository.create_call[6:] == (5, "request-1")


@pytest.mark.asyncio
async def test_expired_acceptance_outcome_is_returned_for_transaction_commit() -> None:
    repository = InvitationRepository()
    repository.accept_result = InvitationAcceptanceExpired()
    use_case = PermissionAdministration(repository)
    actor_id = uuid4()

    result = await use_case.accept_workspace_invitation(actor_id, "opaque-token")

    assert isinstance(result, InvitationAcceptanceExpired)
    assert repository.accept_call == (
        actor_id,
        hashlib.sha256(b"opaque-token").hexdigest(),
    )
