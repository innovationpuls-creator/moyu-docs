from __future__ import annotations

import hashlib
import json
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pytest
import pytest_asyncio
from alembic import command
from alembic.config import Config
from app_core.permission.application.administration import PermissionAdministration
from app_core.permission.domain.access_control import PermissionCapability
from app_core.permission.domain.collaboration import InvitationAcceptanceExpired
from app_infra.postgres.engine import engine
from app_infra.postgres.permission_administration_repository import (
    PostgresPermissionAdministrationRepository,
)
from app_infra.postgres.resource.resource_repository import PostgresResourceRepository
from app_infra.postgres.test_database_guard import require_isolated_database
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

DATABASE_URL = "postgresql+psycopg://torch@localhost:5432/dom_workspace_lifecycle_test"


@pytest_asyncio.fixture(scope="module", autouse=True)
async def migrated_database() -> None:
    database_url = require_isolated_database(os.environ["DATABASE_URL"])
    assert database_url == DATABASE_URL
    identity_engine = create_async_engine(database_url)
    try:
        async with identity_engine.connect() as connection:
            identity = (
                await connection.execute(
                    text("SELECT current_database(), current_user")
                )
            ).one()
    finally:
        await identity_engine.dispose()
    if identity != ("dom_workspace_lifecycle_test", "torch"):
        raise RuntimeError(f"Unexpected database identity: {identity!r}")
    config = Config(str(Path("migrations/postgres/alembic.ini")))
    config.set_main_option("sqlalchemy.url", database_url)
    command.upgrade(config, "head")


@pytest_asyncio.fixture
async def db_session() -> AsyncSession:
    async with engine.connect() as connection:
        transaction = await connection.begin()
        factory = async_sessionmaker(
            bind=connection,
            expire_on_commit=False,
            class_=AsyncSession,
            join_transaction_mode="create_savepoint",
        )
        async with factory() as session:
            yield session
            await session.rollback()
        await transaction.rollback()


@pytest.fixture
def encryption_key() -> bytes:
    return os.urandom(32)


async def _account(session: AsyncSession, email: str | None = None):
    account_id = uuid4()
    account_email = email or f"{account_id}@example.test"
    await session.execute(
        text(
            "INSERT INTO auth.accounts "
            "(account_id, status, primary_email, normalized_email) "
            "VALUES (:id, 'Active', :email, :email)"
        ),
        {"id": account_id, "email": account_email},
    )
    return account_id, account_email


async def _workspace(session: AsyncSession):
    owner_id, _email = await _account(session)
    workspace_id = uuid4()
    await session.execute(
        text(
            "INSERT INTO core.workspaces (workspace_id, name, status, created_by) "
            "VALUES (:id, 'Permission test', 'Active', :owner)"
        ),
        {"id": workspace_id, "owner": owner_id},
    )
    await session.execute(
        text(
            "INSERT INTO core.workspace_members "
            "(workspace_id, account_id, membership_kind) "
            "VALUES (:workspace_id, :owner_id, 'Owner')"
        ),
        {"workspace_id": workspace_id, "owner_id": owner_id},
    )
    return workspace_id, owner_id


@pytest.mark.asyncio
async def test_replaying_invitation_create_returns_original_url_without_rotating_hash(
    db_session: AsyncSession, encryption_key: bytes
) -> None:
    workspace_id, owner_id = await _workspace(db_session)
    repository = PostgresPermissionAdministrationRepository(db_session, encryption_key)
    fixed_now = datetime(2026, 9, 25, tzinfo=UTC)
    first = PermissionAdministration(
        repository, now=lambda: fixed_now, token_factory=lambda _: "first-secret"
    )
    replay = PermissionAdministration(
        repository,
        now=lambda: fixed_now + timedelta(seconds=1),
        token_factory=lambda _: "different-secret",
    )

    created = await first.create_workspace_invitation(
        owner_id, workspace_id, "member@example.test", "key-1", 7
    )
    repeated = await replay.create_workspace_invitation(
        owner_id, workspace_id, "member@example.test", "key-1", 7
    )

    assert repeated.invitation.invitation_id == created.invitation.invitation_id
    assert repeated.invitation_url == created.invitation_url
    row = (
        await db_session.execute(
            text("SELECT token_hash FROM core.invitations WHERE invitation_id=:id"),
            {"id": created.invitation.invitation_id},
        )
    ).one()
    assert row.token_hash == hashlib.sha256(b"first-secret").hexdigest()
    stored_response = await db_session.scalar(
        text(
            "SELECT response FROM integration.idempotency_records "
            "WHERE idempotency_key=:key"
        ),
        {"key": (f"permission:create-invitation:{owner_id}:key-1")},
    )
    assert stored_response is not None
    assert "first-secret" not in stored_response
    assert created.invitation_url not in stored_response
    assert "encryptedInvitationUrl" in json.loads(stored_response)


@pytest.mark.asyncio
async def test_expired_invitation_acceptance_persists_state_and_audit(
    db_session: AsyncSession, encryption_key: bytes
) -> None:
    workspace_id, owner_id = await _workspace(db_session)
    invitee_id, invitee_email = await _account(db_session, "invitee@example.test")
    token = "expired-invitation-secret"
    invitation_id = uuid4()
    await db_session.execute(
        text(
            "INSERT INTO core.invitations "
            "(invitation_id, workspace_id, target_email, role, state, token_hash, "
            "expires_at, created_by) VALUES (:id, :workspace_id, :email, 'Member', "
            "'Pending', :token_hash, :expires_at, :owner_id)"
        ),
        {
            "id": invitation_id,
            "workspace_id": workspace_id,
            "email": invitee_email,
            "token_hash": hashlib.sha256(token.encode()).hexdigest(),
            "expires_at": datetime.now(UTC) - timedelta(minutes=1),
            "owner_id": owner_id,
        },
    )
    repository = PostgresPermissionAdministrationRepository(db_session, encryption_key)

    outcome = await PermissionAdministration(repository).accept_workspace_invitation(
        invitee_id, token
    )

    assert isinstance(outcome, InvitationAcceptanceExpired)
    state = await db_session.scalar(
        text("SELECT state FROM core.invitations WHERE invitation_id=:id"),
        {"id": invitation_id},
    )
    assert state == "Expired"
    audit_count = await db_session.scalar(
        text(
            "SELECT count(*) FROM audit.entries WHERE action="
            "'workspace_invitation_expired' AND target_ref->>'invitationId'=:id"
        ),
        {"id": str(invitation_id)},
    )
    assert audit_count == 1


@pytest.mark.asyncio
async def test_resource_capabilities_respect_project_and_resource_lifecycle(
    db_session: AsyncSession, encryption_key: bytes
) -> None:
    workspace_id, owner_id = await _workspace(db_session)
    project_id = uuid4()
    await db_session.execute(
        text(
            "INSERT INTO core.projects "
            "(project_id, workspace_id, name, normalized_name, lifecycle, "
            "created_by, created_at, updated_at) "
            "VALUES (:id, :workspace_id, 'Lifecycle project', 'lifecycle-project', "
            "'Active', :owner_id, now(), now())"
        ),
        {"id": project_id, "workspace_id": workspace_id, "owner_id": owner_id},
    )
    resource = await PostgresResourceRepository(db_session).create(
        project_id=project_id,
        resource_type="document",
        name="Lifecycle document",
        normalized_name="lifecycle-document",
    )
    repository = PostgresPermissionAdministrationRepository(db_session, encryption_key)

    active = await repository.get_resource_capabilities(owner_id, resource.resource_id)
    assert active is not None
    assert active.allows(PermissionCapability.EDIT)

    await db_session.execute(
        text("UPDATE core.projects SET lifecycle='Archived' WHERE project_id=:id"),
        {"id": project_id},
    )
    archived = await repository.get_resource_capabilities(
        owner_id, resource.resource_id
    )
    assert archived is not None
    assert archived.allows(PermissionCapability.READ)
    assert not archived.allows(PermissionCapability.EDIT)

    await db_session.execute(
        text("UPDATE core.resources SET lifecycle='Trashed' WHERE resource_id=:id"),
        {"id": resource.resource_id},
    )
    trashed = await repository.get_resource_capabilities(owner_id, resource.resource_id)
    assert trashed is None
