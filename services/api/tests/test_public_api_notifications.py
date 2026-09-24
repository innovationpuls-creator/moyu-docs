"""Guarded proof: integration-key signed Public API access (arch 22 PUB-001)."""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

import pytest
from api.dependencies.auth import get_current_session
from api.infra.broadcast import get_broadcast_publisher
from app_core.integrations.domain import sign
from app_infra.postgres.engine import engine
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


@pytest.mark.asyncio
async def test_public_notifications_signed_access() -> None:
    connection = await engine.connect()
    session = AsyncSession(connection)
    try:
        account_id = uuid4()
        async with session.begin():
            await session.execute(
                text(
                    "INSERT INTO auth.accounts "
                    "(account_id,status,primary_email,normalized_email) "
                    "VALUES (:a,'Active',:e,:e)"
                ),
                {"a": account_id, "e": f"pub-{account_id}@test"},
            )
            await session.execute(
                text(
                    "INSERT INTO core.notifications "
                    "(notification_id,account_id,kind,payload,read_at) "
                    "VALUES (:n,:a,'comment.mention','{}'::jsonb,NULL)"
                ),
                {"n": uuid4(), "a": account_id},
            )
        from app_core.integrations.application import IssueApiKey
        from app_infra.postgres.integration_key_repository import (
            PostgresIntegrationKeyRepository,
        )

        async with session.begin():
            key, private = await IssueApiKey(
                PostgresIntegrationKeyRepository(session)
            ).execute(account_id, "machine-a")
        from api.main import create_app

        class _StubPublisher:
            async def publish(self, *_args, **_kwargs):
                return "stub"

        app = create_app(debug=True)
        app.dependency_overrides[get_current_session] = lambda: SimpleNamespace(
            account_id=account_id
        )
        app.dependency_overrides[get_broadcast_publisher] = lambda: _StubPublisher()
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            body: bytes = b""
            now = datetime.now(UTC)
            response = await client.get(
                "/v1/public/notifications",
                headers={
                    "X-Dom-Key-Id": str(key.key_id),
                    "X-Dom-Signature": sign(body, now, private),
                    "X-Dom-Timestamp": str(int(now.timestamp())),
                },
            )
            assert response.status_code == 200, response.text
            items = response.json()["items"]
            assert len(items) == 1
            assert items[0]["kind"] == "comment.mention"
            # wrong signature -> 401
            now2 = datetime.now(UTC)
            forged = await client.get(
                "/v1/public/notifications",
                headers={
                    "X-Dom-Key-Id": str(key.key_id),
                    "X-Dom-Signature": "00" * 64,
                    "X-Dom-Timestamp": str(int(now2.timestamp())),
                },
            )
            assert forged.status_code == 401
            # missing headers -> 401
            missing = await client.get("/v1/public/notifications")
            assert missing.status_code == 401
    finally:
        await session.close()
        await connection.close()


@pytest.mark.asyncio
async def test_api_key_rotation_revokes_old_and_issues_new() -> None:
    connection = await engine.connect()
    session = AsyncSession(connection)
    try:
        account_id = uuid4()
        async with session.begin():
            await session.execute(
                text(
                    "INSERT INTO auth.accounts "
                    "(account_id,status,primary_email,normalized_email) "
                    "VALUES (:a,'Active',:e,:e)"
                ),
                {"a": account_id, "e": f"rot-{account_id}@test"},
            )
        from app_core.integrations.application import IssueApiKey
        from app_infra.postgres.integration_key_repository import (
            PostgresIntegrationKeyRepository,
        )

        async with session.begin():
            old_key, old_private = await IssueApiKey(
                PostgresIntegrationKeyRepository(session)
            ).execute(account_id, "old")
        from api.main import create_app

        class _StubPublisher:
            async def publish(self, *_args, **_kwargs):
                return "stub"

        app = create_app(debug=True)
        app.dependency_overrides[get_current_session] = lambda: SimpleNamespace(
            account_id=account_id
        )
        app.dependency_overrides[get_broadcast_publisher] = lambda: _StubPublisher()
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            rotated = await client.post(
                f"/v1/integrations/api-keys/{old_key.key_id}/rotate",
                json={"label": "new"},
            )
            assert rotated.status_code == 200, rotated.text
            body = rotated.json()
            assert body["revokedKeyId"] == str(old_key.key_id)
            new_private = bytes.fromhex(body["privateKeyHex"])
            # the OLD key no longer verifies; the NEW key does
            from datetime import UTC, datetime

            now_old = datetime.now(UTC)
            old_signed = await client.get(
                "/v1/public/notifications",
                headers={
                    "X-Dom-Key-Id": str(old_key.key_id),
                    "X-Dom-Signature": sign(b"", now_old, old_private),
                    "X-Dom-Timestamp": str(int(now_old.timestamp())),
                },
            )
            assert old_signed.status_code == 401
            now_new = datetime.now(UTC)
            new_signed = await client.get(
                "/v1/public/notifications",
                headers={
                    "X-Dom-Key-Id": body["keyId"],
                    "X-Dom-Signature": sign(b"", now_new, new_private),
                    "X-Dom-Timestamp": str(int(now_new.timestamp())),
                },
            )
            assert new_signed.status_code == 200
    finally:
        await session.close()
        await connection.close()


@pytest.mark.asyncio
async def test_public_resources_readable_scope() -> None:
    """PUB-002: machine key lists OWNED + membership-readable resources only."""
    connection = await engine.connect()
    session = AsyncSession(connection)
    try:
        actor = uuid4()
        stranger = uuid4()
        workspace_id = uuid4()
        project_id = uuid4()
        async with session.begin():
            for a, tag in ((actor, "ar"), (stranger, "st")):
                await session.execute(
                    text(
                        "INSERT INTO auth.accounts "
                        "(account_id,status,primary_email,normalized_email) "
                        "VALUES (:a,'Active',:e,:e)"
                    ),
                    {"a": a, "e": f"{tag}-{a}@test"},
                )
            await session.execute(
                text(
                    "INSERT INTO core.workspaces "
                    "(workspace_id,name,status,created_by,created_at,updated_at) "
                    "VALUES (:w,'S','Active',:a,now(),now())"
                ),
                {"w": workspace_id, "a": actor},
            )
            await session.execute(
                text(
                    "INSERT INTO core.workspace_members "
                    "(workspace_id,account_id,membership_kind) "
                    "VALUES (:w,:a,'Owner')"
                ),
                {"w": workspace_id, "a": actor},
            )
            await session.execute(
                text(
                    "INSERT INTO core.projects "
                    "(project_id,workspace_id,name,normalized_name,lifecycle,"
                    "created_by,created_at,updated_at) "
                    "VALUES (:p,:w,'P','p','Active',:a,now(),now())"
                ),
                {"p": project_id, "w": workspace_id, "a": actor},
            )
            from app_infra.postgres.resource.resource_repository import (
                PostgresResourceRepository,
            )

            mine = await PostgresResourceRepository(session).create(
                project_id=project_id,
                resource_type="document",
                name="Mine",
                normalized_name="mine",
            )
            await session.execute(
                text(
                    "INSERT INTO collab.resource_ownership "
                    "(resource_id,owner_account_id,epoch) VALUES (:r,:a,1)"
                ),
                {"r": mine.resource_id, "a": actor},
            )
            other = await PostgresResourceRepository(session).create(
                project_id=project_id,
                resource_type="document",
                name="Other",
                normalized_name="other",
            )
            await session.execute(
                text(
                    "INSERT INTO collab.resource_ownership "
                    "(resource_id,owner_account_id,epoch) VALUES (:r,:a,1)"
                ),
                {"r": other.resource_id, "a": stranger},
            )
            # a resource in a DIFFERENT workspace (no membership) must stay out
            alien_workspace = uuid4()
            alien_project = uuid4()
            await session.execute(
                text(
                    "INSERT INTO core.workspaces "
                    "(workspace_id,name,status,created_by,created_at,updated_at) "
                    "VALUES (:w,'A','Active',:a,now(),now())"
                ),
                {"w": alien_workspace, "a": stranger},
            )
            await session.execute(
                text(
                    "INSERT INTO core.workspace_members "
                    "(workspace_id,account_id,membership_kind) "
                    "VALUES (:w,:a,'Owner')"
                ),
                {"w": alien_workspace, "a": stranger},
            )
            await session.execute(
                text(
                    "INSERT INTO core.projects "
                    "(project_id,workspace_id,name,normalized_name,lifecycle,"
                    "created_by,created_at,updated_at) "
                    "VALUES (:p,:w,'AP','ap','Active',:a,now(),now())"
                ),
                {"p": alien_project, "w": alien_workspace, "a": stranger},
            )
            await PostgresResourceRepository(session).create(
                project_id=alien_project,
                resource_type="document",
                name="Alien",
                normalized_name="alien",
            )
        from app_core.integrations.application import IssueApiKey
        from app_infra.postgres.integration_key_repository import (
            PostgresIntegrationKeyRepository,
        )

        async with session.begin():
            key, private = await IssueApiKey(
                PostgresIntegrationKeyRepository(session)
            ).execute(actor, "machine-r")
        from api.main import create_app

        class _StubPublisher:
            async def publish(self, *_args, **_kwargs):
                return "stub"

        app = create_app(debug=True)
        app.dependency_overrides[get_current_session] = lambda: SimpleNamespace(
            account_id=actor
        )
        app.dependency_overrides[get_broadcast_publisher] = lambda: _StubPublisher()
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            now = datetime.now(UTC)
            response = await client.get(
                "/v1/public/resources",
                headers={
                    "X-Dom-Key-Id": str(key.key_id),
                    "X-Dom-Signature": sign(b"", now, private),
                    "X-Dom-Timestamp": str(int(now.timestamp())),
                },
            )
        assert response.status_code == 200, response.text
        names = [i["name"] for i in response.json()["items"]]
        assert "Mine" in names  # owned
        assert "Other" in names  # readable via workspace membership
        assert "Alien" not in names  # foreign workspace stays out
    finally:
        await session.close()
        await connection.close()


@pytest.mark.asyncio
async def test_public_api_rate_limit_blocks_after_budget() -> None:
    """Arch 22 hardening: per-owner fixed-window budget; overflow -> 429
    RATE_LIMITED (the canonical RateLimit category code)."""
    connection = await engine.connect()
    session = AsyncSession(connection)
    try:
        actor = uuid4()
        async with session.begin():
            await session.execute(
                text(
                    "INSERT INTO auth.accounts "
                    "(account_id,status,primary_email,normalized_email) "
                    "VALUES (:a,'Active',:e,:e)"
                ),
                {"a": actor, "e": f"rl-{actor}@test"},
            )
        from app_core.integrations.application import IssueApiKey
        from app_infra.postgres.integration_key_repository import (
            PostgresIntegrationKeyRepository,
        )

        async with session.begin():
            key, private = await IssueApiKey(
                PostgresIntegrationKeyRepository(session)
            ).execute(actor, "machine-rl")

        class _FakeValkey:
            store: dict[str, str] = {}

            async def get(self, key: str):
                return self.store.get(key)

            def pipeline(self):
                return _FakePipeline(self.store)

        class _FakePipeline:
            def __init__(self, store: dict):
                self._store = store
                self._ops: list[tuple] = []

            def incr(self, key: str):
                self._ops.append(("incr", key))
                return self

            def expire(self, key: str, seconds: int):
                self._ops.append(("expire", key, seconds))
                return self

            async def execute(self):
                for op in self._ops:
                    if op[0] == "incr":
                        self._store[op[1]] = str(int(self._store.get(op[1], "0")) + 1)
                return [1] * len(self._ops)

        from api.routes import public_api
        from app_infra.valkey.public_rate_limiter import PublicApiRateLimiter

        limiter = PublicApiRateLimiter(_FakeValkey(), limit=2)
        from api.main import create_app

        class _StubPublisher:
            async def publish(self, *_args, **_kwargs):
                return "stub"

        app = create_app(debug=True)
        app.dependency_overrides[get_current_session] = lambda: SimpleNamespace(
            account_id=actor
        )
        app.dependency_overrides[get_broadcast_publisher] = lambda: _StubPublisher()
        app.dependency_overrides[public_api.get_public_rate_limiter] = lambda: limiter
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            now = datetime.now(UTC)
            headers = {
                "X-Dom-Key-Id": str(key.key_id),
                "X-Dom-Signature": sign(b"", now, private),
                "X-Dom-Timestamp": str(int(now.timestamp())),
            }
            first = await client.get("/v1/public/resources", headers=headers)
            second = await client.get("/v1/public/resources", headers=headers)
            third = await client.get("/v1/public/resources", headers=headers)
            assert first.status_code == 200, first.text
            assert second.status_code == 200, second.text
            assert third.status_code == 429, third.text
            assert third.json()["errorCode"] == "RATE_LIMITED"
    finally:
        await session.close()
        await connection.close()
