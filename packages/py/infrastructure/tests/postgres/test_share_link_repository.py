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
from app_core.common.exceptions import PermissionDeniedError
from app_core.permission.application.share_links import ShareLinkAdministration
from app_core.permission.domain.access_control import PermissionCapability
from app_core.permission.domain.share_link import ShareLinkStatus
from app_infra.postgres.engine import engine
from app_infra.postgres.share_link_repository import PostgresShareLinkRepository
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


async def _account(session: AsyncSession) -> object:
    account_id = uuid4()
    email = f"{account_id}@example.test"
    await session.execute(
        text(
            "INSERT INTO auth.accounts "
            "(account_id, status, primary_email, normalized_email) "
            "VALUES (:id, 'Active', :email, :email)"
        ),
        {"id": account_id, "email": email},
    )
    return account_id


async def _resource_scope(session: AsyncSession) -> tuple[object, object, object]:
    owner_id = await _account(session)
    workspace_id, project_id, resource_id = uuid4(), uuid4(), uuid4()
    await session.execute(
        text(
            "INSERT INTO core.workspaces (workspace_id, name, status, created_by) "
            "VALUES (:id, 'Share Link test', 'Active', :owner)"
        ),
        {"id": workspace_id, "owner": owner_id},
    )
    await session.execute(
        text(
            "INSERT INTO core.workspace_members "
            "(workspace_id, account_id, membership_kind) "
            "VALUES (:workspace_id, :owner, 'Owner')"
        ),
        {"workspace_id": workspace_id, "owner": owner_id},
    )
    await session.execute(
        text(
            "INSERT INTO core.projects "
            "(project_id, workspace_id, name, normalized_name, created_by) "
            "VALUES (:id, :workspace_id, 'Share Link project', 'share-link', :owner)"
        ),
        {"id": project_id, "workspace_id": workspace_id, "owner": owner_id},
    )
    await session.execute(
        text(
            "INSERT INTO core.resources "
            "(resource_id, project_id, resource_type, name, "
            "normalized_name, created_by) "
            "VALUES (:id, :project_id, 'document', 'Share Link resource', "
            "'share-link-resource', :owner)"
        ),
        {"id": resource_id, "project_id": project_id, "owner": owner_id},
    )
    return owner_id, project_id, resource_id


@pytest.mark.asyncio
async def test_owner_and_manager_can_manage_readonly_links_and_rotate_secret(
    db_session: AsyncSession, encryption_key: bytes
) -> None:
    owner_id, project_id, resource_id = await _resource_scope(db_session)
    manager_id = await _account(db_session)
    reader_id = await _account(db_session)
    await db_session.execute(
        text(
            "INSERT INTO core.project_members "
            "(project_id, account_id, role, membership_kind) "
            "VALUES (:project_id, :manager, 'Manage', 'Member')"
        ),
        {"project_id": project_id, "manager": manager_id},
    )
    await db_session.execute(
        text(
            "INSERT INTO core.resource_permissions (resource_id, account_id, role) "
            "VALUES (:resource_id, :reader, 'Read')"
        ),
        {"resource_id": resource_id, "reader": reader_id},
    )
    repository = PostgresShareLinkRepository(db_session, encryption_key)
    now = datetime.now(UTC)
    manager_tokens = iter(["manager-secret", "regenerated-secret"])
    owner = ShareLinkAdministration(
        repository,
        now=lambda: now,
        token_factory=lambda _: "owner-secret",
    )
    manager = ShareLinkAdministration(
        repository,
        now=lambda: now,
        token_factory=lambda _: next(manager_tokens),
    )

    owner_link = await owner.create_share_link(
        owner_id, resource_id, "owner-create", now + timedelta(days=3)
    )
    repeated = await ShareLinkAdministration(
        repository,
        now=lambda: now,
        token_factory=lambda _: "unused-secret",
    ).create_share_link(owner_id, resource_id, "owner-create", now + timedelta(days=3))
    manager_link = await manager.create_share_link(
        manager_id, resource_id, "manager-create"
    )

    assert repeated.share_url == owner_link.share_url
    assert owner_link.share_link.status is ShareLinkStatus.ACTIVE
    assert len(await manager.list_share_links(manager_id, resource_id)) == 2
    with pytest.raises(PermissionDeniedError):
        await manager.list_share_links(reader_id, resource_id)

    owner_share_id = owner_link.share_link.share_id
    revoked = await manager.revoke_share_link(
        manager_id, resource_id, owner_share_id, "manager-revoke"
    )
    assert revoked.status is ShareLinkStatus.REVOKED
    assert await owner.resolve_public_share("owner-secret") is None

    rotated = await manager.regenerate_share_link(
        manager_id, resource_id, owner_share_id, None, "manager-rotate"
    )
    assert rotated.share_url == "/share/regenerated-secret"
    assert await owner.resolve_public_share("owner-secret") is None
    manager_grant = await owner.resolve_public_share("manager-secret")
    assert manager_grant is not None
    assert manager_grant.share_id == manager_link.share_link.share_id
    grant = await owner.resolve_public_share("regenerated-secret")
    assert grant is not None
    assert grant.resource_id == resource_id
    assert grant.allows(PermissionCapability.READ)
    assert not grant.allows(PermissionCapability.EDIT)
    assert not grant.allows(PermissionCapability.COMMENT)
    assert not grant.can_participate_in_presence

    stored_hashes = (
        (
            await db_session.execute(
                text(
                    "SELECT token_hash FROM core.share_links "
                    "WHERE resource_id=:resource_id ORDER BY created_at, share_id"
                ),
                {"resource_id": resource_id},
            )
        )
        .scalars()
        .all()
    )
    assert hashlib.sha256(b"regenerated-secret").hexdigest() in stored_hashes
    assert hashlib.sha256(b"owner-secret").hexdigest() not in stored_hashes
    assert "owner-secret" not in repr(stored_hashes)
    assert "regenerated-secret" not in repr(stored_hashes)
    response = await db_session.scalar(
        text(
            "SELECT response FROM integration.idempotency_records "
            "WHERE idempotency_key=:key"
        ),
        {"key": f"permission:create-share-link:{owner_id}:owner-create"},
    )
    assert isinstance(response, str)
    assert owner_link.share_url not in response
    assert "owner-secret" not in response
    assert "encryptedShareUrl" in json.loads(response)
    regenerated_response = await db_session.scalar(
        text(
            "SELECT response FROM integration.idempotency_records "
            "WHERE idempotency_key=:key"
        ),
        {"key": (f"permission:regenerate-share-link:{manager_id}:manager-rotate")},
    )
    assert isinstance(regenerated_response, str)
    assert rotated.share_url not in regenerated_response
    assert "regenerated-secret" not in regenerated_response
    assert "encryptedShareUrl" in json.loads(regenerated_response)
    audit_metadata = (
        (
            await db_session.execute(
                text(
                    "SELECT metadata FROM audit.entries "
                    "WHERE resource_id=:resource_id "
                    "AND action LIKE 'resource_share_link_%'"
                ),
                {"resource_id": resource_id},
            )
        )
        .scalars()
        .all()
    )
    audit_content = json.dumps(audit_metadata)
    assert "owner-secret" not in audit_content
    assert "regenerated-secret" not in audit_content
    assert owner_link.share_url not in audit_content
    assert manager_link.share_url not in audit_content


@pytest.mark.asyncio
async def test_expiry_and_inactive_resource_stop_public_resolution(
    db_session: AsyncSession, encryption_key: bytes
) -> None:
    owner_id, _project_id, resource_id = await _resource_scope(db_session)
    repository = PostgresShareLinkRepository(db_session, encryption_key)
    administration = ShareLinkAdministration(
        repository, token_factory=lambda _: "expiring-secret"
    )
    created = await administration.create_share_link(
        owner_id, resource_id, "expiring-create", datetime.now(UTC) + timedelta(days=1)
    )
    expired_at = datetime.now(UTC) - timedelta(seconds=1)
    await db_session.execute(
        text("UPDATE core.share_links SET expires_at=:expires_at WHERE share_id=:id"),
        {"expires_at": expired_at, "id": created.share_link.share_id},
    )

    status = await administration.get_share_link(
        owner_id, resource_id, created.share_link.share_id
    )
    assert status.status is ShareLinkStatus.EXPIRED
    assert await administration.resolve_public_share("expiring-secret") is None

    await db_session.execute(
        text("UPDATE core.resources SET lifecycle='Trashed' WHERE resource_id=:id"),
        {"id": resource_id},
    )
    assert await administration.resolve_public_share("expiring-secret") is None
