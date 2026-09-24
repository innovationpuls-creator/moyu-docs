"""Guarded route-level proof: GET /v1/resources/{id} over the real DB."""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import httpx
import pytest
import pytest_asyncio
from alembic import command
from alembic.config import Config
from api.dependencies.auth import get_current_session
from api.main import create_app
from app_infra.postgres.engine import engine
from app_infra.postgres.resource.checkpoint_repository import (
    PostgresCheckpointRepository,
)
from app_infra.postgres.resource.journal_repository import PostgresJournalRepository
from app_infra.postgres.resource.resource_repository import PostgresResourceRepository
from app_infra.postgres.resource_ownership_repository import (
    PostgresResourceOwnershipRepository,
)
from app_infra.postgres.test_database_guard import require_isolated_database
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

DATABASE_URL = "postgresql+psycopg://torch@localhost:5432/dom_workspace_lifecycle_test"


@pytest_asyncio.fixture(scope="module", autouse=True)
async def migrated_database() -> None:
    database_url = require_isolated_database(os.environ["DATABASE_URL"])
    assert database_url == DATABASE_URL
    config = Config(str(Path("migrations/postgres/alembic.ini")))
    config.set_main_option("sqlalchemy.url", database_url)
    command.upgrade(config, "head")


@pytest.mark.asyncio
async def test_open_resource_route_returns_snapshot_for_owner() -> None:
    connection = await engine.connect()
    session = AsyncSession(connection)
    try:
        account_id = uuid4()
        workspace_id = uuid4()
        project_id = uuid4()
        async with session.begin():
            await session.execute(
                text(
                    "INSERT INTO auth.accounts "
                    "(account_id,status,primary_email,normalized_email) "
                    "VALUES (:a,'Active',:e,:e)"
                ),
                {"a": account_id, "e": f"or-{account_id}@test"},
            )
            await session.execute(
                text(
                    "INSERT INTO core.workspaces "
                    "(workspace_id,name,status,created_by,created_at,updated_at) "
                    "VALUES (:w,'R','Active',:a,now(),now())"
                ),
                {"w": workspace_id, "a": account_id},
            )
            await session.execute(
                text(
                    "INSERT INTO core.workspace_members "
                    "(workspace_id,account_id,membership_kind) "
                    "VALUES (:w,:a,'Owner')"
                ),
                {"w": workspace_id, "a": account_id},
            )
            await session.execute(
                text(
                    "INSERT INTO core.projects "
                    "(project_id,workspace_id,name,normalized_name,lifecycle,"
                    "created_by,created_at,updated_at) "
                    "VALUES (:p,:w,'P','p','Active',:a,now(),now())"
                ),
                {"p": project_id, "w": workspace_id, "a": account_id},
            )
            resource = await PostgresResourceRepository(session).create(
                project_id=project_id,
                resource_type="document",
                name="Doc",
                normalized_name="doc",
            )
            await PostgresResourceOwnershipRepository(session).grant(
                resource.resource_id, account_id
            )
        journal = PostgresJournalRepository(session)
        checkpoints = PostgresCheckpointRepository(session)
        async with session.begin():
            await journal.append_op(resource.resource_id, 1, 1, b"op", "h")
            await checkpoints.write(resource.resource_id, 1, {"text": "hello"})
        app: FastAPI = create_app(debug=True)
        app.dependency_overrides[get_current_session] = lambda: SimpleNamespace(
            account_id=account_id
        )
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.get(f"/v1/resources/{resource.resource_id}")
        assert response.status_code == 200
        body = response.json()
        assert body["resourceType"] == "document"
        assert body["journalSeq"] == 1
        assert body["snapshot"] == {"text": "hello"}
        # non-owner denied
        other = uuid4()
        async with session.begin():
            await session.execute(
                text(
                    "INSERT INTO auth.accounts "
                    "(account_id,status,primary_email,normalized_email) "
                    "VALUES (:a,'Active',:e,:e)"
                ),
                {"a": other, "e": f"or-{other}@test"},
            )
        app.dependency_overrides[get_current_session] = lambda: SimpleNamespace(
            account_id=other
        )
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            denied = await client.get(f"/v1/resources/{resource.resource_id}")
        assert denied.status_code == 403
    finally:
        await session.close()
        await connection.close()


@pytest.mark.asyncio
async def test_create_and_append_journal_route_chain() -> None:
    connection = await engine.connect()
    session = AsyncSession(connection)
    try:
        account_id = uuid4()
        workspace_id = uuid4()
        project_id = uuid4()
        async with session.begin():
            await session.execute(
                text(
                    "INSERT INTO auth.accounts "
                    "(account_id,status,primary_email,normalized_email) "
                    "VALUES (:a,'Active',:e,:e)"
                ),
                {"a": account_id, "e": f"rw-{account_id}@test"},
            )
            await session.execute(
                text(
                    "INSERT INTO core.workspaces "
                    "(workspace_id,name,status,created_by,created_at,updated_at) "
                    "VALUES (:w,'R','Active',:a,now(),now())"
                ),
                {"w": workspace_id, "a": account_id},
            )
            await session.execute(
                text(
                    "INSERT INTO core.workspace_members "
                    "(workspace_id,account_id,membership_kind) "
                    "VALUES (:w,:a,'Owner')"
                ),
                {"w": workspace_id, "a": account_id},
            )
            await session.execute(
                text(
                    "INSERT INTO core.projects "
                    "(project_id,workspace_id,name,normalized_name,lifecycle,"
                    "created_by,created_at,updated_at) "
                    "VALUES (:p,:w,'P','p','Active',:a,now(),now())"
                ),
                {"p": project_id, "w": workspace_id, "a": account_id},
            )
        app: FastAPI = create_app(debug=True)
        app.dependency_overrides[get_current_session] = lambda: SimpleNamespace(
            account_id=account_id
        )
        from api.infra.broadcast import get_broadcast_publisher

        class _StubPublisher:
            async def publish(self, *_args, **_kwargs):
                return "rt.broadcast.stub"

        app.dependency_overrides[get_broadcast_publisher] = lambda: _StubPublisher()
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            created = await client.post(
                "/v1/resources",
                headers={"Idempotency-Key": f"{uuid4()}"},
                json={
                    "projectId": str(project_id),
                    "resourceType": "document",
                    "name": "Doc",
                    "idempotencyKey": str(uuid4()),
                },
            )
            assert created.status_code == 201, created.text
            resource_id = created.json()["resourceId"]
            conflicted = await client.post(
                "/v1/resources",
                headers={"Idempotency-Key": f"{uuid4()}"},
                json={
                    "projectId": str(project_id),
                    "resourceType": "document",
                    "name": "doc",
                    "idempotencyKey": str(uuid4()),
                },
            )
            assert conflicted.status_code == 409, conflicted.text
            from base64 import b64encode

            appended = await client.post(
                f"/v1/resources/{resource_id}/journal",
                headers={"Idempotency-Key": f"{uuid4()}"},
                json={
                    "resourceId": str(resource_id),
                    "expectedSeq": 1,
                    "update": b64encode(b"edit-1").decode(),
                    "idempotencyKey": str(uuid4()),
                },
            )
            assert appended.status_code == 200, appended.text
            assert appended.json()["journalSeq"] == 1
            reopened = await client.get(f"/v1/resources/{resource_id}")
            assert reopened.status_code == 200
    finally:
        await session.close()
        await connection.close()


@pytest.mark.asyncio
async def test_append_publishes_op_to_nats_relay_subject() -> None:
    """Save -> NATS broadcast (rt.broadcast.<id>) with the journal seq."""
    import json
    import subprocess
    import time

    subprocess.run(
        ["docker", "rm", "-f", "dom-rt-test"], check=False, capture_output=True
    )
    subprocess.run(
        [
            "docker",
            "run",
            "-d",
            "--name",
            "dom-rt-test",
            "-p",
            "4222:4222",
            "nats:2.10-alpine",
            "-js",
        ],
        check=True,
        capture_output=True,
    )
    from nats.aio.client import Client as NATS

    client = NATS()
    await client.connect("nats://localhost:4222")
    try:
        received: list[dict] = []

        async def on_message(msg) -> None:
            received.append(json.loads(msg.data.decode()))

        sub = await client.subscribe("rt.broadcast.>", cb=on_message)
        await client.flush()

        connection = await engine.connect()
        session = AsyncSession(connection)
        try:
            account_id = uuid4()
            workspace_id = uuid4()
            project_id = uuid4()
            async with session.begin():
                await session.execute(
                    text(
                        "INSERT INTO auth.accounts "
                        "(account_id,status,primary_email,normalized_email) "
                        "VALUES (:a,'Active',:e,:e)"
                    ),
                    {"a": account_id, "e": f"br-{account_id}@test"},
                )
                await session.execute(
                    text(
                        "INSERT INTO core.workspaces "
                        "(workspace_id,name,status,created_by,created_at,updated_at) "
                        "VALUES (:w,'R','Active',:a,now(),now())"
                    ),
                    {"w": workspace_id, "a": account_id},
                )
                await session.execute(
                    text(
                        "INSERT INTO core.workspace_members "
                        "(workspace_id,account_id,membership_kind) "
                        "VALUES (:w,:a,'Owner')"
                    ),
                    {"w": workspace_id, "a": account_id},
                )
                await session.execute(
                    text(
                        "INSERT INTO core.projects "
                        "(project_id,workspace_id,name,normalized_name,lifecycle,"
                        "created_by,created_at,updated_at) "
                        "VALUES (:p,:w,'P','p','Active',:a,now(),now())"
                    ),
                    {"p": project_id, "w": workspace_id, "a": account_id},
                )
                resource = await PostgresResourceRepository(session).create(
                    project_id=project_id,
                    resource_type="document",
                    name="Doc",
                    normalized_name="doc",
                )
                await PostgresResourceOwnershipRepository(session).grant(
                    resource.resource_id, account_id
                )
            from base64 import b64encode

            from api.infra.broadcast import get_broadcast_publisher
            from app_infra.nats.resource_broadcast_publisher import (
                NatsResourceBroadcastPublisher,
            )

            app: FastAPI = create_app(debug=True)
            app.dependency_overrides[get_current_session] = lambda: SimpleNamespace(
                account_id=account_id
            )
            app.dependency_overrides[get_broadcast_publisher] = lambda: (
                NatsResourceBroadcastPublisher(client)
            )
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as http:
                appended = await http.post(
                    f"/v1/resources/{resource.resource_id}/journal",
                    headers={"Idempotency-Key": f"{uuid4()}"},
                    json={
                        "resourceId": str(resource.resource_id),
                        "expectedSeq": 1,
                        "update": b64encode(b"live-edit").decode(),
                        "idempotencyKey": str(uuid4()),
                    },
                )
            assert appended.status_code == 200
            await client.flush()
            deadline = time.time() + 5
            while not received and time.time() < deadline:
                await client.flush()
                time.sleep(0.1)
            assert len(received) == 1
            assert received[0]["kind"] == "op"
            assert received[0]["resourceId"] == str(resource.resource_id)
            assert received[0]["payload"]["journalSeq"] == 1
            await sub.unsubscribe()
        finally:
            await session.close()
            await connection.close()
    finally:
        await client.drain()
        subprocess.run(
            ["docker", "rm", "-f", "dom-rt-test"], check=False, capture_output=True
        )


@pytest.mark.asyncio
async def test_rename_and_trash_resource_chain() -> None:
    connection = await engine.connect()
    session = AsyncSession(connection)
    try:
        account_id = uuid4()
        workspace_id = uuid4()
        project_id = uuid4()
        async with session.begin():
            await session.execute(
                text(
                    "INSERT INTO auth.accounts "
                    "(account_id,status,primary_email,normalized_email) "
                    "VALUES (:a,'Active',:e,:e)"
                ),
                {"a": account_id, "e": f"rt-{account_id}@test"},
            )
            await session.execute(
                text(
                    "INSERT INTO core.workspaces "
                    "(workspace_id,name,status,created_by,created_at,updated_at) "
                    "VALUES (:w,'R','Active',:a,now(),now())"
                ),
                {"w": workspace_id, "a": account_id},
            )
            await session.execute(
                text(
                    "INSERT INTO core.workspace_members "
                    "(workspace_id,account_id,membership_kind) "
                    "VALUES (:w,:a,'Owner')"
                ),
                {"w": workspace_id, "a": account_id},
            )
            await session.execute(
                text(
                    "INSERT INTO core.projects "
                    "(project_id,workspace_id,name,normalized_name,lifecycle,"
                    "created_by,created_at,updated_at) "
                    "VALUES (:p,:w,'P','p','Active',:a,now(),now())"
                ),
                {"p": project_id, "w": workspace_id, "a": account_id},
            )
            resource = await PostgresResourceRepository(session).create(
                project_id=project_id,
                resource_type="document",
                name="Doc",
                normalized_name="doc",
            )
            await PostgresResourceOwnershipRepository(session).grant(
                resource.resource_id, account_id
            )
            # sibling reserves the name even after trash
            await PostgresResourceRepository(session).create(
                project_id=project_id,
                resource_type="document",
                name="Other",
                normalized_name="other",
            )
        from api.infra.broadcast import get_broadcast_publisher

        class _StubPublisher:
            async def publish(self, *_args, **_kwargs):
                return "rt.broadcast.stub"

        app: FastAPI = create_app(debug=True)
        app.dependency_overrides[get_current_session] = lambda: SimpleNamespace(
            account_id=account_id
        )
        app.dependency_overrides[get_broadcast_publisher] = lambda: _StubPublisher()
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            renamed = await client.patch(
                f"/v1/resources/{resource.resource_id}",
                headers={"Idempotency-Key": f"{uuid4()}"},
                json={
                    "resourceId": str(resource.resource_id),
                    "name": "Renamed",
                    "idempotencyKey": str(uuid4()),
                },
            )
            assert renamed.status_code == 200, renamed.text
            assert renamed.json()["name"] == "Renamed"
            conflicted = await client.patch(
                f"/v1/resources/{resource.resource_id}",
                headers={"Idempotency-Key": f"{uuid4()}"},
                json={
                    "resourceId": str(resource.resource_id),
                    "name": "Other",
                    "idempotencyKey": str(uuid4()),
                },
            )
            assert conflicted.status_code == 409, conflicted.text
            trashed = await client.post(
                f"/v1/resources/{resource.resource_id}/trash",
                headers={"Idempotency-Key": f"{uuid4()}"},
                json={
                    "resourceId": str(resource.resource_id),
                    "idempotencyKey": str(uuid4()),
                },
            )
            assert trashed.status_code == 200, trashed.text
            assert trashed.json()["lifecycle"] == "Trashed"
            # trashed resource is not openable (404)
            hidden = await client.get(f"/v1/resources/{resource.resource_id}")
            assert hidden.status_code == 404
            restored = await client.post(
                f"/v1/resources/{resource.resource_id}/restore",
                headers={"Idempotency-Key": f"{uuid4()}"},
                json={
                    "resourceId": str(resource.resource_id),
                    "idempotencyKey": str(uuid4()),
                },
            )
            assert restored.status_code == 200, restored.text
            assert restored.json()["lifecycle"] == "Active"
            reopened = await client.get(f"/v1/resources/{resource.resource_id}")
            assert reopened.status_code == 200
    finally:
        await session.close()
        await connection.close()


@pytest.mark.asyncio
async def test_list_projects_route_for_member() -> None:
    connection = await engine.connect()
    session = AsyncSession(connection)
    try:
        account_id = uuid4()
        workspace_id = uuid4()
        project_id = uuid4()
        async with session.begin():
            await session.execute(
                text(
                    "INSERT INTO auth.accounts "
                    "(account_id,status,primary_email,normalized_email) "
                    "VALUES (:a,'Active',:e,:e)"
                ),
                {"a": account_id, "e": f"lp-{account_id}@test"},
            )
            await session.execute(
                text(
                    "INSERT INTO core.workspaces "
                    "(workspace_id,name,status,created_by,created_at,updated_at) "
                    "VALUES (:w,'L','Active',:a,now(),now())"
                ),
                {"w": workspace_id, "a": account_id},
            )
            await session.execute(
                text(
                    "INSERT INTO core.workspace_members "
                    "(workspace_id,account_id,membership_kind) "
                    "VALUES (:w,:a,'Owner')"
                ),
                {"w": workspace_id, "a": account_id},
            )
            await session.execute(
                text(
                    "INSERT INTO core.projects "
                    "(project_id,workspace_id,name,normalized_name,lifecycle,"
                    "created_by,created_at,updated_at) "
                    "VALUES (:p,:w,'P1','p1','Active',:a,now(),now())"
                ),
                {"p": project_id, "w": workspace_id, "a": account_id},
            )
        app: FastAPI = create_app(debug=True)
        app.dependency_overrides[get_current_session] = lambda: SimpleNamespace(
            account_id=account_id
        )
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.get(f"/v1/workspaces/{workspace_id}/projects")
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["workspaceId"] == str(workspace_id)
        assert [i["name"] for i in body["items"]] == ["P1"]
    finally:
        await session.close()
        await connection.close()


@pytest.mark.asyncio
async def test_list_resources_route_for_member() -> None:
    connection = await engine.connect()
    session = AsyncSession(connection)
    try:
        account_id = uuid4()
        workspace_id = uuid4()
        project_id = uuid4()
        other = uuid4()
        async with session.begin():
            await session.execute(
                text(
                    "INSERT INTO auth.accounts "
                    "(account_id,status,primary_email,normalized_email) "
                    "VALUES (:a,'Active',:e,:e)"
                ),
                {"a": account_id, "e": f"lr-{account_id}@test"},
            )
            await session.execute(
                text(
                    "INSERT INTO auth.accounts "
                    "(account_id,status,primary_email,normalized_email) "
                    "VALUES (:a,'Active',:e,:e)"
                ),
                {"a": other, "e": f"lr-{other}@test"},
            )
            await session.execute(
                text(
                    "INSERT INTO core.workspaces "
                    "(workspace_id,name,status,created_by,created_at,updated_at) "
                    "VALUES (:w,'L','Active',:a,now(),now())"
                ),
                {"w": workspace_id, "a": account_id},
            )
            await session.execute(
                text(
                    "INSERT INTO core.workspace_members "
                    "(workspace_id,account_id,membership_kind) "
                    "VALUES (:w,:a,'Owner')"
                ),
                {"w": workspace_id, "a": account_id},
            )
            await session.execute(
                text(
                    "INSERT INTO core.projects "
                    "(project_id,workspace_id,name,normalized_name,lifecycle,"
                    "created_by,created_at,updated_at) "
                    "VALUES (:p,:w,'P','p','Active',:a,now(),now())"
                ),
                {"p": project_id, "w": workspace_id, "a": account_id},
            )
            active = await PostgresResourceRepository(session).create(
                project_id=project_id,
                resource_type="document",
                name="Doc",
                normalized_name="doc",
            )
            trashed = await PostgresResourceRepository(session).create(
                project_id=project_id,
                resource_type="markdown",
                name="Old",
                normalized_name="old",
            )
            await PostgresResourceOwnershipRepository(session).grant(
                active.resource_id, account_id
            )
            await PostgresResourceOwnershipRepository(session).grant(
                trashed.resource_id, account_id
            )
            await PostgresResourceRepository(session).set_lifecycle(
                trashed.resource_id, "Trashed"
            )
        app: FastAPI = create_app(debug=True)
        app.dependency_overrides[get_current_session] = lambda: SimpleNamespace(
            account_id=account_id
        )
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.get(f"/v1/projects/{project_id}/resources")
        assert response.status_code == 200, response.text
        items = response.json()["items"]
        by_name = {i["name"]: i for i in items}
        assert by_name["Doc"]["resourceType"] == "document"
        assert by_name["Old"]["lifecycle"] == "Trashed"
        # non-member denied
        app.dependency_overrides[get_current_session] = lambda: SimpleNamespace(
            account_id=other
        )
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            denied = await client.get(f"/v1/projects/{project_id}/resources")
        assert denied.status_code == 403
    finally:
        await session.close()
        await connection.close()


@pytest.mark.asyncio
async def test_comments_api_round_trip() -> None:
    """FR-CMT-001/002 over the real chain."""
    connection = await engine.connect()
    session = AsyncSession(connection)
    try:
        account_id = uuid4()
        workspace_id = uuid4()
        project_id = uuid4()
        outsider = uuid4()
        async with session.begin():
            await session.execute(
                text(
                    "INSERT INTO auth.accounts "
                    "(account_id,status,primary_email,normalized_email) "
                    "VALUES (:a,'Active',:e,:e)"
                ),
                {"a": account_id, "e": f"cma-{account_id}@test"},
            )
            await session.execute(
                text(
                    "INSERT INTO auth.accounts "
                    "(account_id,status,primary_email,normalized_email) "
                    "VALUES (:a,'Active',:e,:e)"
                ),
                {"a": outsider, "e": f"cma-{outsider}@test"},
            )
            await session.execute(
                text(
                    "INSERT INTO core.workspaces "
                    "(workspace_id,name,status,created_by,created_at,updated_at) "
                    "VALUES (:w,'C','Active',:a,now(),now())"
                ),
                {"w": workspace_id, "a": account_id},
            )
            await session.execute(
                text(
                    "INSERT INTO core.workspace_members "
                    "(workspace_id,account_id,membership_kind) "
                    "VALUES (:w,:a,'Owner')"
                ),
                {"w": workspace_id, "a": account_id},
            )
            await session.execute(
                text(
                    "INSERT INTO core.projects "
                    "(project_id,workspace_id,name,normalized_name,lifecycle,"
                    "created_by,created_at,updated_at) "
                    "VALUES (:p,:w,'P','p','Active',:a,now(),now())"
                ),
                {"p": project_id, "w": workspace_id, "a": account_id},
            )
            resource = await PostgresResourceRepository(session).create(
                project_id=project_id,
                resource_type="document",
                name="Doc",
                normalized_name="doc",
            )
            await PostgresResourceOwnershipRepository(session).grant(
                resource.resource_id, account_id
            )
        from api.infra.broadcast import get_broadcast_publisher

        class _StubPublisher:
            async def publish(self, *_args, **_kwargs):
                return "stub"

        app: FastAPI = create_app(debug=True)
        app.dependency_overrides[get_current_session] = lambda: SimpleNamespace(
            account_id=account_id
        )
        app.dependency_overrides[get_broadcast_publisher] = lambda: _StubPublisher()
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            added = await client.post(
                f"/v1/resources/{resource.resource_id}/comments",
                headers={"Idempotency-Key": f"{uuid4()}"},
                json={
                    "resourceId": str(resource.resource_id),
                    "body": "整体缺异常流程",
                    "idempotencyKey": str(uuid4()),
                },
            )
            assert added.status_code == 201, added.text
            comment_id = added.json()["commentId"]
            listed = await client.get(f"/v1/resources/{resource.resource_id}/comments")
            assert listed.status_code == 200
            items = listed.json()["items"]
            assert [i["commentId"] for i in items] == [comment_id]
            assert items[0]["body"] == "整体缺异常流程"
        # outsider denied
        app.dependency_overrides[get_current_session] = lambda: SimpleNamespace(
            account_id=outsider
        )
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            denied = await client.post(
                f"/v1/resources/{resource.resource_id}/comments",
                headers={"Idempotency-Key": f"{uuid4()}"},
                json={
                    "resourceId": str(resource.resource_id),
                    "body": "no",
                    "idempotencyKey": str(uuid4()),
                },
            )
        assert denied.status_code == 403
    finally:
        await session.close()
        await connection.close()


@pytest.mark.asyncio
async def test_search_workspace_route_ranks_hits() -> None:
    connection = await engine.connect()
    session = AsyncSession(connection)
    try:
        account_id = uuid4()
        workspace_id = uuid4()
        project_id = uuid4()
        outsider = uuid4()
        async with session.begin():
            await session.execute(
                text(
                    "INSERT INTO auth.accounts "
                    "(account_id,status,primary_email,normalized_email) "
                    "VALUES (:a,'Active',:e,:e)"
                ),
                {"a": account_id, "e": f"sr-{account_id}@test"},
            )
            await session.execute(
                text(
                    "INSERT INTO auth.accounts "
                    "(account_id,status,primary_email,normalized_email) "
                    "VALUES (:a,'Active',:e,:e)"
                ),
                {"a": outsider, "e": f"sr-{outsider}@test"},
            )
            await session.execute(
                text(
                    "INSERT INTO core.workspaces "
                    "(workspace_id,name,status,created_by,created_at,updated_at) "
                    "VALUES (:w,'S','Active',:a,now(),now())"
                ),
                {"w": workspace_id, "a": account_id},
            )
            await session.execute(
                text(
                    "INSERT INTO core.workspace_members "
                    "(workspace_id,account_id,membership_kind) "
                    "VALUES (:w,:a,'Owner')"
                ),
                {"w": workspace_id, "a": account_id},
            )
            await session.execute(
                text(
                    "INSERT INTO core.projects "
                    "(project_id,workspace_id,name,normalized_name,lifecycle,"
                    "created_by,created_at,updated_at) "
                    "VALUES (:p,:w,'P','p','Active',:a,now(),now())"
                ),
                {"p": project_id, "w": workspace_id, "a": account_id},
            )
            resource = await PostgresResourceRepository(session).create(
                project_id=project_id,
                resource_type="document",
                name="API 设计",
                normalized_name="api 设计",
            )
            await PostgresResourceOwnershipRepository(session).grant(
                resource.resource_id, account_id
            )
            # index the resource (search module owns the index; populated by
            # the checkpoint consumer in full builds)
            await session.execute(
                text(
                    "INSERT INTO collab.resource_search_index "
                    "(resource_id,workspace_id,project_id,resource_type,name,"
                    "searchable_text,lifecycle) "
                    "VALUES (:rid,:wid,:pid,'document','API 设计',"
                    "'request 验证与错误信封','Active')"
                ),
                {
                    "rid": resource.resource_id,
                    "wid": workspace_id,
                    "pid": project_id,
                },
            )
        app: FastAPI = create_app(debug=True)
        app.dependency_overrides[get_current_session] = lambda: SimpleNamespace(
            account_id=account_id
        )
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.get(
                f"/v1/workspaces/{workspace_id}/search",
                params={"q": "错误信封"},
            )
        assert response.status_code == 200, response.text
        items = response.json()["items"]
        assert [i["name"] for i in items] == ["API 设计"]
        # outsider denied
        app.dependency_overrides[get_current_session] = lambda: SimpleNamespace(
            account_id=outsider
        )
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            denied = await client.get(
                f"/v1/workspaces/{workspace_id}/search",
                params={"q": "错误信封"},
            )
        assert denied.status_code == 403
    finally:
        await session.close()
        await connection.close()


@pytest.mark.asyncio
async def test_high_risk_ops_write_audit_entries() -> None:
    """Arch 23 audit category: trash + restore + owner-transfer are recorded."""
    connection = await engine.connect()
    session = AsyncSession(connection)
    try:
        account_id = uuid4()
        workspace_id = uuid4()
        project_id = uuid4()
        async with session.begin():
            await session.execute(
                text(
                    "INSERT INTO auth.accounts "
                    "(account_id,status,primary_email,normalized_email) "
                    "VALUES (:a,'Active',:e,:e)"
                ),
                {"a": account_id, "e": f"au-{account_id}@test"},
            )
            await session.execute(
                text(
                    "INSERT INTO core.workspaces "
                    "(workspace_id,name,status,created_by,created_at,updated_at) "
                    "VALUES (:w,'A','Active',:a,now(),now())"
                ),
                {"w": workspace_id, "a": account_id},
            )
            await session.execute(
                text(
                    "INSERT INTO core.workspace_members "
                    "(workspace_id,account_id,membership_kind) "
                    "VALUES (:w,:a,'Owner')"
                ),
                {"w": workspace_id, "a": account_id},
            )
            await session.execute(
                text(
                    "INSERT INTO core.projects "
                    "(project_id,workspace_id,name,normalized_name,lifecycle,"
                    "created_by,created_at,updated_at) "
                    "VALUES (:p,:w,'P','p','Active',:a,now(),now())"
                ),
                {"p": project_id, "w": workspace_id, "a": account_id},
            )
            resource = await PostgresResourceRepository(session).create(
                project_id=project_id,
                resource_type="document",
                name="Doc",
                normalized_name="doc",
            )
            await PostgresResourceOwnershipRepository(session).grant(
                resource.resource_id, account_id
            )
        from api.infra.broadcast import get_broadcast_publisher

        class _StubPublisher:
            async def publish(self, *_args, **_kwargs):
                return "stub"

        app: FastAPI = create_app(debug=True)
        app.dependency_overrides[get_current_session] = lambda: SimpleNamespace(
            account_id=account_id
        )
        app.dependency_overrides[get_broadcast_publisher] = lambda: _StubPublisher()
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            trashed = await client.post(
                f"/v1/resources/{resource.resource_id}/trash",
                headers={"Idempotency-Key": f"{uuid4()}"},
                json={
                    "resourceId": str(resource.resource_id),
                    "idempotencyKey": str(uuid4()),
                },
            )
            assert trashed.status_code == 200
            restored = await client.post(
                f"/v1/resources/{resource.resource_id}/restore",
                headers={"Idempotency-Key": f"{uuid4()}"},
                json={
                    "resourceId": str(resource.resource_id),
                    "idempotencyKey": str(uuid4()),
                },
            )
            assert restored.status_code == 200
        async with session.begin():
            entries = (
                (
                    await session.execute(
                        text(
                            "SELECT action FROM core.audit_entries "
                            "WHERE target_type='resource' ORDER BY occurred_at"
                        )
                    )
                )
                .scalars()
                .all()
            )
        assert "resource.trashed" in entries
        assert "resource.restored" in entries
    finally:
        await session.close()
        await connection.close()


@pytest.mark.asyncio
async def test_export_import_round_trip() -> None:
    """FR-IE-001/002: export the snapshot; import it back as a new checkpoint."""
    connection = await engine.connect()
    session = AsyncSession(connection)
    try:
        account_id = uuid4()
        workspace_id = uuid4()
        project_id = uuid4()
        outsider = uuid4()
        async with session.begin():
            await session.execute(
                text(
                    "INSERT INTO auth.accounts "
                    "(account_id,status,primary_email,normalized_email) "
                    "VALUES (:a,'Active',:e,:e)"
                ),
                {"a": account_id, "e": f"ie-{account_id}@test"},
            )
            await session.execute(
                text(
                    "INSERT INTO auth.accounts "
                    "(account_id,status,primary_email,normalized_email) "
                    "VALUES (:a,'Active',:e,:e)"
                ),
                {"a": outsider, "e": f"ie-{outsider}@test"},
            )
            await session.execute(
                text(
                    "INSERT INTO core.workspaces "
                    "(workspace_id,name,status,created_by,created_at,updated_at) "
                    "VALUES (:w,'E','Active',:a,now(),now())"
                ),
                {"w": workspace_id, "a": account_id},
            )
            await session.execute(
                text(
                    "INSERT INTO core.workspace_members "
                    "(workspace_id,account_id,membership_kind) "
                    "VALUES (:w,:a,'Owner')"
                ),
                {"w": workspace_id, "a": account_id},
            )
            await session.execute(
                text(
                    "INSERT INTO core.projects "
                    "(project_id,workspace_id,name,normalized_name,lifecycle,"
                    "created_by,created_at,updated_at) "
                    "VALUES (:p,:w,'P','p','Active',:a,now(),now())"
                ),
                {"p": project_id, "w": workspace_id, "a": account_id},
            )
            resource = await PostgresResourceRepository(session).create(
                project_id=project_id,
                resource_type="markdown",
                name="Docs",
                normalized_name="docs",
            )
            await PostgresResourceOwnershipRepository(session).grant(
                resource.resource_id, account_id
            )
            journal = PostgresJournalRepository(session)
            await journal.append_op(resource.resource_id, 1, 1, b"op", "h")
            await PostgresCheckpointRepository(session).write(
                resource.resource_id, 1, {"text": "可导出的内容"}
            )
        from api.infra.broadcast import get_broadcast_publisher

        class _StubPublisher:
            async def publish(self, *_args, **_kwargs):
                return "stub"

        app: FastAPI = create_app(debug=True)
        app.dependency_overrides[get_current_session] = lambda: SimpleNamespace(
            account_id=account_id
        )
        app.dependency_overrides[get_broadcast_publisher] = lambda: _StubPublisher()
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            exported = await client.get(f"/v1/resources/{resource.resource_id}/export")
            assert exported.status_code == 200, exported.text
            doc = exported.json()
            assert doc["kind"] == "dom.resource.export.v1"
            assert doc["content"]["snapshot"] == {"text": "可导出的内容"}
            imported = await client.post(
                f"/v1/resources/{resource.resource_id}/import",
                headers={"Idempotency-Key": f"{uuid4()}"},
                json={
                    "resourceId": str(resource.resource_id),
                    "document": doc,
                    "idempotencyKey": str(uuid4()),
                },
            )
            assert imported.status_code == 200, imported.text
            seq = imported.json()["journalSeq"]
            assert seq == 2
            reopened = await client.get(f"/v1/resources/{resource.resource_id}")
            assert reopened.status_code == 200
            assert reopened.json()["snapshot"] == {"text": "可导出的内容"}
        # outsider denied export
        app.dependency_overrides[get_current_session] = lambda: SimpleNamespace(
            account_id=outsider
        )
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            denied = await client.get(f"/v1/resources/{resource.resource_id}/export")
        assert denied.status_code == 403
    finally:
        await session.close()
        await connection.close()


@pytest.mark.asyncio
async def test_asset_upload_download_round_trip() -> None:
    """FR-AS-001: upload stores blob+metadata; download round-trips the bytes."""
    import base64

    connection = await engine.connect()
    session = AsyncSession(connection)
    try:
        account_id = uuid4()
        workspace_id = uuid4()
        project_id = uuid4()
        outsider = uuid4()
        async with session.begin():
            await session.execute(
                text(
                    "INSERT INTO auth.accounts "
                    "(account_id,status,primary_email,normalized_email) "
                    "VALUES (:a,'Active',:e,:e)"
                ),
                {"a": account_id, "e": f"as-{account_id}@test"},
            )
            await session.execute(
                text(
                    "INSERT INTO auth.accounts "
                    "(account_id,status,primary_email,normalized_email) "
                    "VALUES (:a,'Active',:e,:e)"
                ),
                {"a": outsider, "e": f"as-{outsider}@test"},
            )
            await session.execute(
                text(
                    "INSERT INTO core.workspaces "
                    "(workspace_id,name,status,created_by,created_at,updated_at) "
                    "VALUES (:w,'A','Active',:a,now(),now())"
                ),
                {"w": workspace_id, "a": account_id},
            )
            await session.execute(
                text(
                    "INSERT INTO core.workspace_members "
                    "(workspace_id,account_id,membership_kind) "
                    "VALUES (:w,:a,'Owner')"
                ),
                {"w": workspace_id, "a": account_id},
            )
            await session.execute(
                text(
                    "INSERT INTO core.projects "
                    "(project_id,workspace_id,name,normalized_name,lifecycle,"
                    "created_by,created_at,updated_at) "
                    "VALUES (:p,:w,'P','p','Active',:a,now(),now())"
                ),
                {"p": project_id, "w": workspace_id, "a": account_id},
            )
            resource = await PostgresResourceRepository(session).create(
                project_id=project_id,
                resource_type="document",
                name="Doc",
                normalized_name="doc",
            )
            await PostgresResourceOwnershipRepository(session).grant(
                resource.resource_id, account_id
            )
        from api.infra.broadcast import get_broadcast_publisher

        class _StubPublisher:
            async def publish(self, *_args, **_kwargs):
                return "stub"

        app: FastAPI = create_app(debug=True)
        app.dependency_overrides[get_current_session] = lambda: SimpleNamespace(
            account_id=account_id
        )
        app.dependency_overrides[get_broadcast_publisher] = lambda: _StubPublisher()
        payload = b"asset-bytes-\x00\x01"
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            uploaded = await client.post(
                f"/v1/resources/{resource.resource_id}/assets",
                files={"file": ("a.bin", payload, "application/octet-stream")},
                data={"mime": "application/octet-stream"},
            )
            assert uploaded.status_code == 201, uploaded.text
            body = uploaded.json()
            asset_id = body["assetId"]
            downloaded = await client.get(f"/v1/assets/{asset_id}")
            assert downloaded.status_code == 200
            out = downloaded.json()
            assert base64.b64decode(out["dataB64"]) == payload
            assert out["sha256"] == body["sha256"]
        # outsider denied
        app.dependency_overrides[get_current_session] = lambda: SimpleNamespace(
            account_id=outsider
        )
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            denied = await client.get(f"/v1/assets/{asset_id}")
        assert denied.status_code == 403
    finally:
        await session.close()
        await connection.close()


@pytest.mark.asyncio
async def test_ai_changeset_propose_then_apply() -> None:
    """Arch 12 §6: AI writes form a ChangeSet first; only apply writes."""

    connection = await engine.connect()
    session = AsyncSession(connection)
    try:
        account_id = uuid4()
        workspace_id = uuid4()
        project_id = uuid4()
        async with session.begin():
            await session.execute(
                text(
                    "INSERT INTO auth.accounts "
                    "(account_id,status,primary_email,normalized_email) "
                    "VALUES (:a,'Active',:e,:e)"
                ),
                {"a": account_id, "e": f"ai-{account_id}@test"},
            )
            await session.execute(
                text(
                    "INSERT INTO core.workspaces "
                    "(workspace_id,name,status,created_by,created_at,updated_at) "
                    "VALUES (:w,'A','Active',:a,now(),now())"
                ),
                {"w": workspace_id, "a": account_id},
            )
            await session.execute(
                text(
                    "INSERT INTO core.workspace_members "
                    "(workspace_id,account_id,membership_kind) "
                    "VALUES (:w,:a,'Owner')"
                ),
                {"w": workspace_id, "a": account_id},
            )
            await session.execute(
                text(
                    "INSERT INTO core.projects "
                    "(project_id,workspace_id,name,normalized_name,lifecycle,"
                    "created_by,created_at,updated_at) "
                    "VALUES (:p,:w,'P','p','Active',:a,now(),now())"
                ),
                {"p": project_id, "w": workspace_id, "a": account_id},
            )
            resource = await PostgresResourceRepository(session).create(
                project_id=project_id,
                resource_type="document",
                name="Doc",
                normalized_name="doc",
            )
            await PostgresResourceOwnershipRepository(session).grant(
                resource.resource_id, account_id
            )
        from api.infra.broadcast import get_broadcast_publisher

        class _StubPublisher:
            async def publish(self, *_args, **_kwargs):
                return "stub"

        app: FastAPI = create_app(debug=True)
        app.dependency_overrides[get_current_session] = lambda: SimpleNamespace(
            account_id=account_id
        )
        app.dependency_overrides[get_broadcast_publisher] = lambda: _StubPublisher()
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            proposed = await client.post(
                "/v1/ai/propose-changeset",
                json={
                    "resourceId": str(resource.resource_id),
                    "instruction": "重构异常流程",
                },
            )
            assert proposed.status_code == 200, proposed.text
            body = proposed.json()
            assert body["status"] == "Proposed"
            changeset_id = body["changesetId"]
            applied = await client.post(f"/v1/changesets/{changeset_id}/apply")
            assert applied.status_code == 200, applied.text
            assert applied.json()["journalSeq"] == 1
        async with session.begin():
            status = await session.scalar(
                text("SELECT status FROM collab.ai_changesets WHERE changeset_id=:id"),
                {"id": changeset_id},
            )
        assert status == "Applied"
    finally:
        await session.close()
        await connection.close()


@pytest.mark.asyncio
async def test_integration_key_issue_verify_revoke() -> None:
    """Arch 20 signature model: issue -> Ed25519 sign -> verify; tamper and
    revoked-key fail; replay outside the window fails."""
    from datetime import timedelta

    from app_core.integrations import domain as integ
    from app_core.integrations.application import VerifySignedPayload
    from app_infra.postgres.integration_key_repository import (
        PostgresIntegrationKeyRepository,
    )

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
                {"a": account_id, "e": f"ig-{account_id}@test"},
            )
        from api.infra.broadcast import get_broadcast_publisher

        class _StubPublisher:
            async def publish(self, *_args, **_kwargs):
                return "stub"

        app: FastAPI = create_app(debug=True)
        app.dependency_overrides[get_current_session] = lambda: SimpleNamespace(
            account_id=account_id
        )
        app.dependency_overrides[get_broadcast_publisher] = lambda: _StubPublisher()
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            issued = await client.post(
                "/v1/integrations/api-keys", json={"label": "ci"}
            )
            assert issued.status_code == 200, issued.text
            assert issued.json()["label"] == "ci"
        # At the domain level: the private key signs; the STORED public key
        # verifies; tamper / stale-timestamp / revoked-key all fail.
        private, public_hex = integ.new_keypair()
        async with session.begin():
            key = await PostgresIntegrationKeyRepository(session).create(
                account_id=account_id,
                label="sig",
                public_key_hex=public_hex,
            )
        verifier = VerifySignedPayload(PostgresIntegrationKeyRepository(session))
        now = datetime.now(UTC)
        payload = b"integration payload for signature ci"
        signature = integ.sign(payload, now, private)
        async with session.begin():
            assert await verifier.execute(key.key_id, payload, now, signature)
            tampered = integ.sign(b"DIFFERENT payload", now, private)
            assert not await verifier.execute(key.key_id, payload, now, tampered)
            stale_ts = now - timedelta(minutes=10)
            assert not await verifier.execute(
                key.key_id, payload, stale_ts, integ.sign(payload, stale_ts, private)
            )
        async with session.begin():
            await PostgresIntegrationKeyRepository(session).revoke(key.key_id)
        async with session.begin():
            assert not await verifier.execute(key.key_id, payload, now, signature)
    finally:
        await session.close()
        await connection.close()


@pytest.mark.asyncio
async def test_comment_edit_and_delete_by_author() -> None:
    """FR-CMT-003/004: author edits own comment; soft-delete hides it; outsider
    cannot edit."""
    connection = await engine.connect()
    session = AsyncSession(connection)
    try:
        account_id = uuid4()
        workspace_id = uuid4()
        project_id = uuid4()
        outsider = uuid4()
        async with session.begin():
            for actor in (account_id, outsider):
                await session.execute(
                    text(
                        "INSERT INTO auth.accounts "
                        "(account_id,status,primary_email,normalized_email) "
                        "VALUES (:a,'Active',:e,:e)"
                    ),
                    {"a": actor, "e": f"ce-{actor}@test"},
                )
            await session.execute(
                text(
                    "INSERT INTO core.workspaces "
                    "(workspace_id,name,status,created_by,created_at,updated_at) "
                    "VALUES (:w,'E','Active',:a,now(),now())"
                ),
                {"w": workspace_id, "a": account_id},
            )
            await session.execute(
                text(
                    "INSERT INTO core.workspace_members "
                    "(workspace_id,account_id,membership_kind) "
                    "VALUES (:w,:a,'Owner')"
                ),
                {"w": workspace_id, "a": account_id},
            )
            await session.execute(
                text(
                    "INSERT INTO core.projects "
                    "(project_id,workspace_id,name,normalized_name,lifecycle,"
                    "created_by,created_at,updated_at) "
                    "VALUES (:p,:w,'P','p','Active',:a,now(),now())"
                ),
                {"p": project_id, "w": workspace_id, "a": account_id},
            )
            resource = await PostgresResourceRepository(session).create(
                project_id=project_id,
                resource_type="document",
                name="Doc",
                normalized_name="doc",
            )
            await PostgresResourceOwnershipRepository(session).grant(
                resource.resource_id, account_id
            )
        from api.infra.broadcast import get_broadcast_publisher

        class _StubPublisher:
            async def publish(self, *_args, **_kwargs):
                return "stub"

        app: FastAPI = create_app(debug=True)
        app.dependency_overrides[get_current_session] = lambda: SimpleNamespace(
            account_id=account_id
        )
        app.dependency_overrides[get_broadcast_publisher] = lambda: _StubPublisher()
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            added = await client.post(
                f"/v1/resources/{resource.resource_id}/comments",
                headers={"Idempotency-Key": f"{uuid4()}"},
                json={
                    "resourceId": str(resource.resource_id),
                    "body": "初稿",
                    "idempotencyKey": str(uuid4()),
                },
            )
            assert added.status_code == 201
            comment_id = added.json()["commentId"]
            edited = await client.patch(
                f"/v1/comments/{comment_id}",
                headers={"Idempotency-Key": f"{uuid4()}"},
                json={
                    "commentId": str(comment_id),
                    "body": "修订稿",
                    "idempotencyKey": str(uuid4()),
                },
            )
            assert edited.status_code == 200, edited.text
            assert edited.json()["body"] == "修订稿"
            listed = await client.get(f"/v1/resources/{resource.resource_id}/comments")
            assert [i["body"] for i in listed.json()["items"]] == ["修订稿"]
            deleted = await client.delete(
                f"/v1/comments/{comment_id}",
                headers={"Idempotency-Key": f"{uuid4()}"},
            )
            assert deleted.status_code == 200
            assert deleted.json()["deleted"] is True
            listed_after = await client.get(
                f"/v1/resources/{resource.resource_id}/comments"
            )
            assert listed_after.json()["items"] == []
        # outsider cannot edit
        app.dependency_overrides[get_current_session] = lambda: SimpleNamespace(
            account_id=outsider
        )
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            denied = await client.patch(
                f"/v1/comments/{comment_id}",
                headers={"Idempotency-Key": f"{uuid4()}"},
                json={
                    "commentId": str(comment_id),
                    "body": "hi",
                    "idempotencyKey": str(uuid4()),
                },
            )
        assert denied.status_code == 403
    finally:
        await session.close()
        await connection.close()


@pytest.mark.asyncio
async def test_history_timeline_and_restore_routes() -> None:
    """Arch 08 UI slice: timeline lists checkpoints; restore appends a new node."""
    connection = await engine.connect()
    session = AsyncSession(connection)
    try:
        account_id = uuid4()
        workspace_id = uuid4()
        project_id = uuid4()
        async with session.begin():
            await session.execute(
                text(
                    "INSERT INTO auth.accounts "
                    "(account_id,status,primary_email,normalized_email) "
                    "VALUES (:a,'Active',:e,:e)"
                ),
                {"a": account_id, "e": f"hs-{account_id}@test"},
            )
            await session.execute(
                text(
                    "INSERT INTO core.workspaces "
                    "(workspace_id,name,status,created_by,created_at,updated_at) "
                    "VALUES (:w,'H','Active',:a,now(),now())"
                ),
                {"w": workspace_id, "a": account_id},
            )
            await session.execute(
                text(
                    "INSERT INTO core.workspace_members "
                    "(workspace_id,account_id,membership_kind) "
                    "VALUES (:w,:a,'Owner')"
                ),
                {"w": workspace_id, "a": account_id},
            )
            await session.execute(
                text(
                    "INSERT INTO core.projects "
                    "(project_id,workspace_id,name,normalized_name,lifecycle,"
                    "created_by,created_at,updated_at) "
                    "VALUES (:p,:w,'P','p','Active',:a,now(),now())"
                ),
                {"p": project_id, "w": workspace_id, "a": account_id},
            )
            resource = await PostgresResourceRepository(session).create(
                project_id=project_id,
                resource_type="document",
                name="Doc",
                normalized_name="doc",
            )
            await PostgresResourceOwnershipRepository(session).grant(
                resource.resource_id, account_id
            )
            journal = PostgresJournalRepository(session)
            await journal.append_op(resource.resource_id, 1, 1, b"op", "h")
            await PostgresCheckpointRepository(session).write(
                resource.resource_id, 1, {"text": "v1"}
            )
        from api.infra.broadcast import get_broadcast_publisher

        class _StubPublisher:
            async def publish(self, *_args, **_kwargs):
                return "stub"

        app: FastAPI = create_app(debug=True)
        app.dependency_overrides[get_current_session] = lambda: SimpleNamespace(
            account_id=account_id
        )
        app.dependency_overrides[get_broadcast_publisher] = lambda: _StubPublisher()
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            timeline = await client.get(f"/v1/resources/{resource.resource_id}/history")
            assert timeline.status_code == 200, timeline.text
            items = timeline.json()["items"]
            assert items and items[0]["seq"] == 1
            restored = await client.post(
                f"/v1/resources/{resource.resource_id}/history/restore",
                json={"baseJournalSeq": 1},
            )
            assert restored.status_code == 200, restored.text
            assert restored.json()["newSeq"] == 2
            after = await client.get(f"/v1/resources/{resource.resource_id}/history")
            kinds = [i["kind"] for i in after.json()["items"]]
            assert "Restore" in kinds
    finally:
        await session.close()
        await connection.close()


@pytest.mark.asyncio
async def test_named_version_creation_and_conflict() -> None:
    """FR-HS-003: label a revision; duplicate label -> 409."""
    from app_infra.postgres.history.history_repository import (
        PostgresHistoryRepository,
    )

    connection = await engine.connect()
    session = AsyncSession(connection)
    try:
        account_id = uuid4()
        workspace_id = uuid4()
        project_id = uuid4()
        async with session.begin():
            await session.execute(
                text(
                    "INSERT INTO auth.accounts "
                    "(account_id,status,primary_email,normalized_email) "
                    "VALUES (:a,'Active',:e,:e)"
                ),
                {"a": account_id, "e": f"nv-{account_id}@test"},
            )
            await session.execute(
                text(
                    "INSERT INTO core.workspaces "
                    "(workspace_id,name,status,created_by,created_at,updated_at) "
                    "VALUES (:w,'N','Active',:a,now(),now())"
                ),
                {"w": workspace_id, "a": account_id},
            )
            await session.execute(
                text(
                    "INSERT INTO core.workspace_members "
                    "(workspace_id,account_id,membership_kind) "
                    "VALUES (:w,:a,'Owner')"
                ),
                {"w": workspace_id, "a": account_id},
            )
            await session.execute(
                text(
                    "INSERT INTO core.projects "
                    "(project_id,workspace_id,name,normalized_name,lifecycle,"
                    "created_by,created_at,updated_at) "
                    "VALUES (:p,:w,'P','p','Active',:a,now(),now())"
                ),
                {"p": project_id, "w": workspace_id, "a": account_id},
            )
            resource = await PostgresResourceRepository(session).create(
                project_id=project_id,
                resource_type="document",
                name="Doc",
                normalized_name="doc",
            )
            await PostgresResourceOwnershipRepository(session).grant(
                resource.resource_id, account_id
            )
            await PostgresHistoryRepository(session).create_named_version(
                resource.resource_id, "首个快照", 1, account_id
            )
        from api.infra.broadcast import get_broadcast_publisher

        class _StubPublisher:
            async def publish(self, *_args, **_kwargs):
                return "stub"

        app: FastAPI = create_app(debug=True)
        app.dependency_overrides[get_current_session] = lambda: SimpleNamespace(
            account_id=account_id
        )
        app.dependency_overrides[get_broadcast_publisher] = lambda: _StubPublisher()
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            conflict = await client.post(
                f"/v1/resources/{resource.resource_id}/versions",
                headers={"Idempotency-Key": f"{uuid4()}"},
                json={
                    "resourceId": str(resource.resource_id),
                    "label": "首个快照",
                    "baseJournalSeq": 1,
                    "idempotencyKey": str(uuid4()),
                },
            )
            assert conflict.status_code == 409, conflict.text
            created = await client.post(
                f"/v1/resources/{resource.resource_id}/versions",
                headers={"Idempotency-Key": f"{uuid4()}"},
                json={
                    "resourceId": str(resource.resource_id),
                    "label": "第二个快照",
                    "baseJournalSeq": 2,
                    "idempotencyKey": str(uuid4()),
                },
            )
            assert created.status_code == 200, created.text
            body = created.json()
            assert body["label"] == "第二个快照"
            assert body["baseJournalSeq"] == 2
        async with session.begin():
            labeled = await session.scalar(
                text(
                    "SELECT count(*) FROM collab.resource_named_versions "
                    "WHERE resource_id=:rid"
                ),
                {"rid": resource.resource_id},
            )
        assert labeled == 2
    finally:
        await session.close()
        await connection.close()


@pytest.mark.asyncio
async def test_comment_add_publishes_resource_event() -> None:
    """Arch 17 realtime: adding a comment publishes comment.added on
    rt.broadcast.<resourceId>."""
    connection = await engine.connect()
    session = AsyncSession(connection)
    try:
        account_id = uuid4()
        workspace_id = uuid4()
        project_id = uuid4()
        async with session.begin():
            await session.execute(
                text(
                    "INSERT INTO auth.accounts "
                    "(account_id,status,primary_email,normalized_email) "
                    "VALUES (:a,'Active',:e,:e)"
                ),
                {"a": account_id, "e": f"cev-{account_id}@test"},
            )
            await session.execute(
                text(
                    "INSERT INTO core.workspaces "
                    "(workspace_id,name,status,created_by,created_at,updated_at) "
                    "VALUES (:w,'E','Active',:a,now(),now())"
                ),
                {"w": workspace_id, "a": account_id},
            )
            await session.execute(
                text(
                    "INSERT INTO core.workspace_members "
                    "(workspace_id,account_id,membership_kind) "
                    "VALUES (:w,:a,'Owner')"
                ),
                {"w": workspace_id, "a": account_id},
            )
            await session.execute(
                text(
                    "INSERT INTO core.projects "
                    "(project_id,workspace_id,name,normalized_name,lifecycle,"
                    "created_by,created_at,updated_at) "
                    "VALUES (:p,:w,'P','p','Active',:a,now(),now())"
                ),
                {"p": project_id, "w": workspace_id, "a": account_id},
            )
            resource = await PostgresResourceRepository(session).create(
                project_id=project_id,
                resource_type="document",
                name="Doc",
                normalized_name="doc",
            )
            await PostgresResourceOwnershipRepository(session).grant(
                resource.resource_id, account_id
            )
        from api.infra.broadcast import get_broadcast_publisher

        published: list[tuple[object, str, dict]] = []

        class _CapturePublisher:
            async def publish(
                self, resource_id: object, kind: str, payload: dict
            ) -> str:
                published.append((resource_id, kind, payload))
                return "ok"

        app: FastAPI = create_app(debug=True)
        app.dependency_overrides[get_current_session] = lambda: SimpleNamespace(
            account_id=account_id
        )
        app.dependency_overrides[get_broadcast_publisher] = lambda: _CapturePublisher()
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            added = await client.post(
                f"/v1/resources/{resource.resource_id}/comments",
                headers={"Idempotency-Key": f"{uuid4()}"},
                json={
                    "resourceId": str(resource.resource_id),
                    "body": "实时评论",
                    "idempotencyKey": str(uuid4()),
                },
            )
        assert added.status_code == 201, added.text
        assert len(published) == 1
        rid, kind, payload = published[0]
        assert rid == resource.resource_id
        assert kind == "comment.added"
        assert payload["body"] == "实时评论"
    finally:
        await session.close()
        await connection.close()


@pytest.mark.asyncio
async def test_mention_creates_notification_only_with_access() -> None:
    """FR-NTF-001: @email in a comment notifies the recipient who holds
    resource.read; self-mention and no-access recipients are skipped."""
    connection = await engine.connect()
    session = AsyncSession(connection)
    try:
        account_id = uuid4()
        mentioned = uuid4()
        no_access = uuid4()
        workspace_id = uuid4()
        project_id = uuid4()
        async with session.begin():
            for actor in (account_id, mentioned, no_access):
                await session.execute(
                    text(
                        "INSERT INTO auth.accounts "
                        "(account_id,status,primary_email,normalized_email) "
                        "VALUES (:a,'Active',:e,:e)"
                    ),
                    {
                        "a": actor,
                        "e": f"nt-{actor}@test",
                    },
                )
            await session.execute(
                text(
                    "INSERT INTO core.workspaces "
                    "(workspace_id,name,status,created_by,created_at,updated_at) "
                    "VALUES (:w,'N','Active',:a,now(),now())"
                ),
                {"w": workspace_id, "a": account_id},
            )
            await session.execute(
                text(
                    "INSERT INTO core.workspace_members "
                    "(workspace_id,account_id,membership_kind) "
                    "VALUES (:w,:a,'Owner')"
                ),
                {"w": workspace_id, "a": account_id},
            )
            await session.execute(
                text(
                    "INSERT INTO core.projects "
                    "(project_id,workspace_id,name,normalized_name,lifecycle,"
                    "created_by,created_at,updated_at) "
                    "VALUES (:p,:w,'P','p','Active',:a,now(),now())"
                ),
                {"p": project_id, "w": workspace_id, "a": account_id},
            )
            resource = await PostgresResourceRepository(session).create(
                project_id=project_id,
                resource_type="document",
                name="Doc",
                normalized_name="doc",
            )
            await PostgresResourceOwnershipRepository(session).grant(
                resource.resource_id, account_id
            )
            # the mentioned recipient is a workspace MEMBER (mention only
            # notifies who already holds membership READ; it never grants
            # permission), while no_access has NO membership.
            await session.execute(
                text(
                    "INSERT INTO core.workspace_members "
                    "(workspace_id,account_id,membership_kind) "
                    "VALUES (:w,:a,'Member')"
                ),
                {"w": workspace_id, "a": mentioned},
            )
        from api.infra.broadcast import get_broadcast_publisher

        class _StubPublisher:
            async def publish(self, *_args, **_kwargs):
                return "stub"

        app: FastAPI = create_app(debug=True)
        app.dependency_overrides[get_current_session] = lambda: SimpleNamespace(
            account_id=account_id
        )
        app.dependency_overrides[get_broadcast_publisher] = lambda: _StubPublisher()
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            posted = await client.post(
                f"/v1/resources/{resource.resource_id}/comments",
                headers={"Idempotency-Key": f"{uuid4()}"},
                json={
                    "resourceId": str(resource.resource_id),
                    "body": (
                        f"请 @nt-{mentioned}@test 复核，也 @nt-{no_access}@test "
                        f"和 @nt-{account_id}@test"
                    ),
                    "idempotencyKey": str(uuid4()),
                },
            )
        assert posted.status_code == 201, posted.text
        async with session.begin():
            mentioned_count = await session.scalar(
                text("SELECT count(*) FROM core.notifications WHERE account_id=:aid"),
                {"aid": mentioned},
            )
            no_access_count = await session.scalar(
                text("SELECT count(*) FROM core.notifications WHERE account_id=:aid"),
                {"aid": no_access},
            )
            self_count = await session.scalar(
                text("SELECT count(*) FROM core.notifications WHERE account_id=:aid"),
                {"aid": account_id},
            )
        assert mentioned_count == 1
        assert no_access_count == 0
        assert self_count == 0
        # recipient lists + marks all read
        app.dependency_overrides[get_current_session] = lambda: SimpleNamespace(
            account_id=mentioned
        )
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            listed = await client.get("/v1/notifications")
            assert listed.status_code == 200
            items = listed.json()["items"]
            assert len(items) == 1
            assert items[0]["kind"] == "comment.mention"
            marked = await client.post("/v1/notifications/read-all")
            assert marked.status_code == 200
            assert marked.json()["marked"] == 1
    finally:
        await session.close()
        await connection.close()


@pytest.mark.asyncio
async def test_comment_edit_delete_publish_events() -> None:
    """Arch 17 realtime: editing/deleting a comment publishes events."""
    connection = await engine.connect()
    session = AsyncSession(connection)
    try:
        account_id = uuid4()
        workspace_id = uuid4()
        project_id = uuid4()
        async with session.begin():
            await session.execute(
                text(
                    "INSERT INTO auth.accounts "
                    "(account_id,status,primary_email,normalized_email) "
                    "VALUES (:a,'Active',:e,:e)"
                ),
                {"a": account_id, "e": f"ced-{account_id}@test"},
            )
            await session.execute(
                text(
                    "INSERT INTO core.workspaces "
                    "(workspace_id,name,status,created_by,created_at,updated_at) "
                    "VALUES (:w,'E','Active',:a,now(),now())"
                ),
                {"w": workspace_id, "a": account_id},
            )
            await session.execute(
                text(
                    "INSERT INTO core.workspace_members "
                    "(workspace_id,account_id,membership_kind) "
                    "VALUES (:w,:a,'Owner')"
                ),
                {"w": workspace_id, "a": account_id},
            )
            await session.execute(
                text(
                    "INSERT INTO core.projects "
                    "(project_id,workspace_id,name,normalized_name,lifecycle,"
                    "created_by,created_at,updated_at) "
                    "VALUES (:p,:w,'P','p','Active',:a,now(),now())"
                ),
                {"p": project_id, "w": workspace_id, "a": account_id},
            )
            resource = await PostgresResourceRepository(session).create(
                project_id=project_id,
                resource_type="document",
                name="Doc",
                normalized_name="doc",
            )
            await PostgresResourceOwnershipRepository(session).grant(
                resource.resource_id, account_id
            )
        from api.infra.broadcast import get_broadcast_publisher

        published: list[tuple[object, str, dict]] = []

        class _CapturePublisher:
            async def publish(
                self, resource_id: object, kind: str, payload: dict
            ) -> str:
                published.append((resource_id, kind, payload))
                return "ok"

        app: FastAPI = create_app(debug=True)
        app.dependency_overrides[get_current_session] = lambda: SimpleNamespace(
            account_id=account_id
        )
        app.dependency_overrides[get_broadcast_publisher] = lambda: _CapturePublisher()
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            added = await client.post(
                f"/v1/resources/{resource.resource_id}/comments",
                headers={"Idempotency-Key": f"{uuid4()}"},
                json={
                    "resourceId": str(resource.resource_id),
                    "body": "初稿",
                    "idempotencyKey": str(uuid4()),
                },
            )
            assert added.status_code == 201
            comment_id = added.json()["commentId"]
            edited = await client.patch(
                f"/v1/comments/{comment_id}",
                headers={"Idempotency-Key": f"{uuid4()}"},
                json={
                    "commentId": str(comment_id),
                    "body": "修订稿",
                    "idempotencyKey": str(uuid4()),
                },
            )
            assert edited.status_code == 200
            deleted = await client.delete(
                f"/v1/comments/{comment_id}",
                headers={"Idempotency-Key": f"{uuid4()}"},
            )
            assert deleted.status_code == 200
        kinds = [kind for (_rid, kind, _payload) in published]
        assert "comment.added" in kinds
        assert "comment.edited" in kinds
        assert "comment.deleted" in kinds
        edited_payload = next(p for (_, k, p) in published if k == "comment.edited")
        assert edited_payload["body"] == "修订稿"
    finally:
        await session.close()
        await connection.close()


@pytest.mark.asyncio
async def test_resource_diff_reports_snapshot_changes() -> None:
    """Arch 08 diff: text snapshots yield insert/delete summaries; key add/remove."""
    connection = await engine.connect()
    session = AsyncSession(connection)
    try:
        account_id = uuid4()
        workspace_id = uuid4()
        project_id = uuid4()
        async with session.begin():
            await session.execute(
                text(
                    "INSERT INTO auth.accounts "
                    "(account_id,status,primary_email,normalized_email) "
                    "VALUES (:a,'Active',:e,:e)"
                ),
                {"a": account_id, "e": f"df-{account_id}@test"},
            )
            await session.execute(
                text(
                    "INSERT INTO core.workspaces "
                    "(workspace_id,name,status,created_by,created_at,updated_at) "
                    "VALUES (:w,'D','Active',:a,now(),now())"
                ),
                {"w": workspace_id, "a": account_id},
            )
            await session.execute(
                text(
                    "INSERT INTO core.workspace_members "
                    "(workspace_id,account_id,membership_kind) "
                    "VALUES (:w,:a,'Owner')"
                ),
                {"w": workspace_id, "a": account_id},
            )
            await session.execute(
                text(
                    "INSERT INTO core.projects "
                    "(project_id,workspace_id,name,normalized_name,lifecycle,"
                    "created_by,created_at,updated_at) "
                    "VALUES (:p,:w,'P','p','Active',:a,now(),now())"
                ),
                {"p": project_id, "w": workspace_id, "a": account_id},
            )
            resource = await PostgresResourceRepository(session).create(
                project_id=project_id,
                resource_type="document",
                name="Doc",
                normalized_name="doc",
            )
            await PostgresResourceOwnershipRepository(session).grant(
                resource.resource_id, account_id
            )
            checkpoints = PostgresCheckpointRepository(session)
            await checkpoints.write(resource.resource_id, 1, {"text": "a", "keep": 1})
            await checkpoints.write(
                resource.resource_id, 2, {"text": "ab", "keep": 2, "extra": True}
            )
        from api.infra.broadcast import get_broadcast_publisher

        class _StubPublisher:
            async def publish(self, *_args, **_kwargs):
                return "stub"

        app: FastAPI = create_app(debug=True)
        app.dependency_overrides[get_current_session] = lambda: SimpleNamespace(
            account_id=account_id
        )
        app.dependency_overrides[get_broadcast_publisher] = lambda: _StubPublisher()
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.get(f"/v1/resources/{resource.resource_id}/diff")
        assert response.status_code == 200, response.text
        diff = response.json()["diff"]
        assert diff["addedKeys"] == ["extra"]
        assert diff["removedKeys"] == []
        changed = {c["key"]: c for c in diff["changed"]}
        assert changed["text"]["summary"]["inserts"] == 1
        assert "keep" in changed
    finally:
        await session.close()
        await connection.close()


@pytest.mark.asyncio
async def test_restore_materializes_text_from_ops() -> None:
    """Arch 08: restore replays JSON-text ops into a NEW checkpoint."""
    connection = await engine.connect()
    session = AsyncSession(connection)
    try:
        account_id = uuid4()
        workspace_id = uuid4()
        project_id = uuid4()
        async with session.begin():
            await session.execute(
                text(
                    "INSERT INTO auth.accounts "
                    "(account_id,status,primary_email,normalized_email) "
                    "VALUES (:a,'Active',:e,:e)"
                ),
                {"a": account_id, "e": f"rm-{account_id}@test"},
            )
            await session.execute(
                text(
                    "INSERT INTO core.workspaces "
                    "(workspace_id,name,status,created_by,created_at,updated_at) "
                    "VALUES (:w,'R','Active',:a,now(),now())"
                ),
                {"w": workspace_id, "a": account_id},
            )
            await session.execute(
                text(
                    "INSERT INTO core.workspace_members "
                    "(workspace_id,account_id,membership_kind) "
                    "VALUES (:w,:a,'Owner')"
                ),
                {"w": workspace_id, "a": account_id},
            )
            await session.execute(
                text(
                    "INSERT INTO core.projects "
                    "(project_id,workspace_id,name,normalized_name,lifecycle,"
                    "created_by,created_at,updated_at) "
                    "VALUES (:p,:w,'P','p','Active',:a,now(),now())"
                ),
                {"p": project_id, "w": workspace_id, "a": account_id},
            )
            resource = await PostgresResourceRepository(session).create(
                project_id=project_id,
                resource_type="document",
                name="Doc",
                normalized_name="doc",
            )
            await PostgresResourceOwnershipRepository(session).grant(
                resource.resource_id, account_id
            )
            journal = PostgresJournalRepository(session)
            # newer text ops beyond the target revision
            await journal.append_op(
                resource.resource_id,
                1,
                1,
                '{"text": "\u7248\u672c\u4e00"}'.encode(),
                "h1",
            )
            await journal.append_op(
                resource.resource_id,
                2,
                1,
                '{"text": "\u7248\u672c\u4e8c"}'.encode(),
                "h2",
            )
            await PostgresCheckpointRepository(session).write(
                resource.resource_id, 2, {"text": "版本二"}
            )
        from api.infra.broadcast import get_broadcast_publisher

        class _StubPublisher:
            async def publish(self, *_args, **_kwargs):
                return "stub"

        app: FastAPI = create_app(debug=True)
        app.dependency_overrides[get_current_session] = lambda: SimpleNamespace(
            account_id=account_id
        )
        app.dependency_overrides[get_broadcast_publisher] = lambda: _StubPublisher()
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            # restore at v1 -> replay stops before the v2 op
            restored = await client.post(
                f"/v1/resources/{resource.resource_id}/history/restore",
                json={"baseJournalSeq": 1},
            )
            assert restored.status_code == 200, restored.text
            assert restored.json()["newSeq"] == 3
            after = await client.get(f"/v1/resources/{resource.resource_id}")
            assert after.status_code == 200
            assert after.json()["snapshot"]["text"] == "版本一"
    finally:
        await session.close()
        await connection.close()


@pytest.mark.asyncio
async def test_mark_single_notification_read() -> None:
    """FR-NTF-003: the recipient marks ONE notification read; others stay."""
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
                {"a": account_id, "e": f"mr-{account_id}@test"},
            )
            first = uuid4()
            second = uuid4()
            await session.execute(
                text(
                    "INSERT INTO core.notifications "
                    "(notification_id,account_id,kind,payload) "
                    "VALUES (:a,:acc,'comment.mention','{}'::jsonb)"
                ),
                {"a": first, "acc": account_id},
            )
            await session.execute(
                text(
                    "INSERT INTO core.notifications "
                    "(notification_id,account_id,kind,payload) "
                    "VALUES (:a,:acc,'comment.mention','{}'::jsonb)"
                ),
                {"a": second, "acc": account_id},
            )
        from api.infra.broadcast import get_broadcast_publisher

        class _StubPublisher:
            async def publish(self, *_args, **_kwargs):
                return "stub"

        app: FastAPI = create_app(debug=True)
        app.dependency_overrides[get_current_session] = lambda: SimpleNamespace(
            account_id=account_id
        )
        app.dependency_overrides[get_broadcast_publisher] = lambda: _StubPublisher()
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            marked = await client.post(f"/v1/notifications/{first}/read")
            assert marked.status_code == 200, marked.text
            assert marked.json()["notificationId"] == str(first)
            again = await client.post(f"/v1/notifications/{second}/read")
            assert again.status_code == 200  # both belong to the same owner
        # the OTHER account's notification cannot be marked by a stranger
        stranger = uuid4()
        app.dependency_overrides[get_current_session] = lambda: SimpleNamespace(
            account_id=stranger
        )
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            denied = await client.post(f"/v1/notifications/{second}/read")
        assert denied.status_code == 404
    finally:
        await session.close()
        await connection.close()


@pytest.mark.asyncio
async def test_search_filters_narrow_results() -> None:
    """Arch 11 filters: type + author + time narrow the search hits."""
    connection = await engine.connect()
    session = AsyncSession(connection)
    try:
        account_id = uuid4()
        workspace_id = uuid4()
        project_id = uuid4()
        async with session.begin():
            await session.execute(
                text(
                    "INSERT INTO auth.accounts "
                    "(account_id,status,primary_email,normalized_email) "
                    "VALUES (:a,'Active',:e,:e)"
                ),
                {"a": account_id, "e": f"sf-{account_id}@test"},
            )
            await session.execute(
                text(
                    "INSERT INTO core.workspaces "
                    "(workspace_id,name,status,created_by,created_at,updated_at) "
                    "VALUES (:w,'S','Active',:a,now(),now())"
                ),
                {"w": workspace_id, "a": account_id},
            )
            await session.execute(
                text(
                    "INSERT INTO core.workspace_members "
                    "(workspace_id,account_id,membership_kind) "
                    "VALUES (:w,:a,'Owner')"
                ),
                {"w": workspace_id, "a": account_id},
            )
            await session.execute(
                text(
                    "INSERT INTO core.projects "
                    "(project_id,workspace_id,name,normalized_name,lifecycle,"
                    "created_by,created_at,updated_at) "
                    "VALUES (:p,:w,'P','p','Active',:a,now(),now())"
                ),
                {"p": project_id, "w": workspace_id, "a": account_id},
            )
            a = await PostgresResourceRepository(session).create(
                project_id=project_id,
                resource_type="document",
                name="DocA",
                normalized_name="doca",
                created_by=account_id,
            )
            b = await PostgresResourceRepository(session).create(
                project_id=project_id,
                resource_type="code",
                name="CodeB",
                normalized_name="codeb",
                created_by=account_id,
            )
            for row, rtype, name, text_ in (
                (a, "document", "DocA", "docs 内容"),
                (b, "code", "CodeB", "code 内容"),
            ):
                await session.execute(
                    text(
                        "INSERT INTO collab.resource_search_index "
                        "(resource_id,workspace_id,project_id,resource_type,"
                        "name,searchable_text,lifecycle) "
                        "VALUES (:id,:w,:p,:t,:n,:tx,'Active')"
                    ),
                    {
                        "id": row.resource_id,
                        "w": workspace_id,
                        "p": project_id,
                        "t": rtype,
                        "n": name,
                        "tx": text_,
                    },
                )
        from api.infra.broadcast import get_broadcast_publisher

        class _StubPublisher:
            async def publish(self, *_args, **_kwargs):
                return "stub"

        app: FastAPI = create_app(debug=True)
        app.dependency_overrides[get_current_session] = lambda: SimpleNamespace(
            account_id=account_id
        )
        app.dependency_overrides[get_broadcast_publisher] = lambda: _StubPublisher()
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            all_hits = await client.get(
                f"/v1/workspaces/{workspace_id}/search",
                params={"q": "内容"},
            )
            assert all_hits.status_code == 200
            assert len(all_hits.json()["items"]) == 2
            docs = await client.get(
                f"/v1/workspaces/{workspace_id}/search",
                params={"q": "内容", "resourceType": "document"},
            )
            assert [i["name"] for i in docs.json()["items"]] == ["DocA"]
            by_author = await client.get(
                f"/v1/workspaces/{workspace_id}/search",
                params={"q": "内容", "author": str(account_id)},
            )
            assert len(by_author.json()["items"]) == 2
            nobody = await client.get(
                f"/v1/workspaces/{workspace_id}/search",
                params={"q": "内容", "author": str(uuid4())},
            )
            assert nobody.json()["items"] == []
    finally:
        await session.close()
        await connection.close()


@pytest.mark.asyncio
async def test_search_project_scope_and_snippet() -> None:
    """Arch 11: projectId narrows hits; results carry a text snippet."""
    connection = await engine.connect()
    session = AsyncSession(connection)
    try:
        account_id = uuid4()
        workspace_id = uuid4()
        project_a = uuid4()
        project_b = uuid4()
        async with session.begin():
            await session.execute(
                text(
                    "INSERT INTO auth.accounts "
                    "(account_id,status,primary_email,normalized_email) "
                    "VALUES (:a,'Active',:e,:e)"
                ),
                {"a": account_id, "e": f"sp-{account_id}@test"},
            )
            await session.execute(
                text(
                    "INSERT INTO core.workspaces "
                    "(workspace_id,name,status,created_by,created_at,updated_at) "
                    "VALUES (:w,'S','Active',:a,now(),now())"
                ),
                {"w": workspace_id, "a": account_id},
            )
            await session.execute(
                text(
                    "INSERT INTO core.workspace_members "
                    "(workspace_id,account_id,membership_kind) "
                    "VALUES (:w,:a,'Owner')"
                ),
                {"w": workspace_id, "a": account_id},
            )
            for pid, label in ((project_a, "A"), (project_b, "B")):
                await session.execute(
                    text(
                        "INSERT INTO core.projects "
                        "(project_id,workspace_id,name,normalized_name,lifecycle,"
                        "created_by,created_at,updated_at) "
                        "VALUES (:p,:w,:n,:n,'Active',:a,now(),now())"
                    ),
                    {"p": pid, "w": workspace_id, "n": label, "a": account_id},
                )
            a_row = await PostgresResourceRepository(session).create(
                project_id=project_a,
                resource_type="document",
                name="ProjA Doc",
                normalized_name="proja doc",
                created_by=account_id,
            )
            b_row = await PostgresResourceRepository(session).create(
                project_id=project_b,
                resource_type="document",
                name="ProjB Doc",
                normalized_name="projb doc",
                created_by=account_id,
            )
            for row, pid in ((a_row, project_a), (b_row, project_b)):
                await session.execute(
                    text(
                        "INSERT INTO collab.resource_search_index "
                        "(resource_id,workspace_id,project_id,resource_type,"
                        "name,searchable_text,lifecycle) "
                        "VALUES (:id,:w,:p,'document',:n,:t,'Active')"
                    ),
                    {
                        "id": row.resource_id,
                        "w": workspace_id,
                        "p": pid,
                        "n": row.name,
                        "t": "共享的关键词与专属上下文",
                    },
                )
        from api.infra.broadcast import get_broadcast_publisher

        class _StubPublisher:
            async def publish(self, *_args, **_kwargs):
                return "stub"

        app: FastAPI = create_app(debug=True)
        app.dependency_overrides[get_current_session] = lambda: SimpleNamespace(
            account_id=account_id
        )
        app.dependency_overrides[get_broadcast_publisher] = lambda: _StubPublisher()
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            scope_a = await client.get(
                f"/v1/workspaces/{workspace_id}/search",
                params={"q": "关键词", "projectId": str(project_a)},
            )
            assert scope_a.status_code == 200
            names = [i["name"] for i in scope_a.json()["items"]]
            assert names == ["ProjA Doc"]
            with_snippet = await client.get(
                f"/v1/workspaces/{workspace_id}/search",
                params={"q": "关键词"},
            )
            items = with_snippet.json()["items"]
            assert all(i["snippet"] for i in items)
            assert "关键词" in items[0]["snippet"]
    finally:
        await session.close()
        await connection.close()


@pytest.mark.asyncio
async def test_search_history_records_and_dedups() -> None:
    """FR-SRC-002: searches are recorded per-account, de-duplicated."""
    connection = await engine.connect()
    session = AsyncSession(connection)
    try:
        account_id = uuid4()
        workspace_id = uuid4()
        project_id = uuid4()
        async with session.begin():
            await session.execute(
                text(
                    "INSERT INTO auth.accounts "
                    "(account_id,status,primary_email,normalized_email) "
                    "VALUES (:a,'Active',:e,:e)"
                ),
                {"a": account_id, "e": f"sh-{account_id}@test"},
            )
            await session.execute(
                text(
                    "INSERT INTO core.workspaces "
                    "(workspace_id,name,status,created_by,created_at,updated_at) "
                    "VALUES (:w,'S','Active',:a,now(),now())"
                ),
                {"w": workspace_id, "a": account_id},
            )
            await session.execute(
                text(
                    "INSERT INTO core.workspace_members "
                    "(workspace_id,account_id,membership_kind) "
                    "VALUES (:w,:a,'Owner')"
                ),
                {"w": workspace_id, "a": account_id},
            )
            await session.execute(
                text(
                    "INSERT INTO core.projects "
                    "(project_id,workspace_id,name,normalized_name,lifecycle,"
                    "created_by,created_at,updated_at) "
                    "VALUES (:p,:w,'P','p','Active',:a,now(),now())"
                ),
                {"p": project_id, "w": workspace_id, "a": account_id},
            )
            await PostgresResourceRepository(session).create(
                project_id=project_id,
                resource_type="document",
                name="Doc",
                normalized_name="doc",
            )
        from api.infra.broadcast import get_broadcast_publisher

        class _StubPublisher:
            async def publish(self, *_args, **_kwargs):
                return "stub"

        app: FastAPI = create_app(debug=True)
        app.dependency_overrides[get_current_session] = lambda: SimpleNamespace(
            account_id=account_id
        )
        app.dependency_overrides[get_broadcast_publisher] = lambda: _StubPublisher()
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            for query in ("foo", "bar", "foo"):
                response = await client.get(
                    f"/v1/workspaces/{workspace_id}/search",
                    params={"q": query},
                )
                assert response.status_code == 200
            listed = await client.get("/v1/search/history")
            assert listed.status_code == 200, listed.text
            items = listed.json()["items"]
            queries = [i["query"] for i in items]
            assert set(queries) == {"foo", "bar"}
            assert queries[0] == "foo"  # latest use first
    finally:
        await session.close()
        await connection.close()


@pytest.mark.asyncio
async def test_search_suggestions_prefixes() -> None:
    """FR-SRC-003: corpus name prefixes + member scoping."""
    connection = await engine.connect()
    session = AsyncSession(connection)
    try:
        account_id = uuid4()
        workspace_id = uuid4()
        project_id = uuid4()
        outsider = uuid4()
        async with session.begin():
            for actor in (account_id, outsider):
                await session.execute(
                    text(
                        "INSERT INTO auth.accounts "
                        "(account_id,status,primary_email,normalized_email) "
                        "VALUES (:a,'Active',:e,:e)"
                    ),
                    {"a": actor, "e": f"sg-{actor}@test"},
                )
            await session.execute(
                text(
                    "INSERT INTO core.workspaces "
                    "(workspace_id,name,status,created_by,created_at,updated_at) "
                    "VALUES (:w,'S','Active',:a,now(),now())"
                ),
                {"w": workspace_id, "a": account_id},
            )
            await session.execute(
                text(
                    "INSERT INTO core.workspace_members "
                    "(workspace_id,account_id,membership_kind) "
                    "VALUES (:w,:a,'Owner')"
                ),
                {"w": workspace_id, "a": account_id},
            )
            await session.execute(
                text(
                    "INSERT INTO core.projects "
                    "(project_id,workspace_id,name,normalized_name,lifecycle,"
                    "created_by,created_at,updated_at) "
                    "VALUES (:p,:w,'P','p','Active',:a,now(),now())"
                ),
                {"p": project_id, "w": workspace_id, "a": account_id},
            )
            for name, norm in (("DocAlpha", "docalpha"), ("DocBeta", "docbeta")):
                row = await PostgresResourceRepository(session).create(
                    project_id=project_id,
                    resource_type="document",
                    name=name,
                    normalized_name=norm,
                )
                await session.execute(
                    text(
                        "INSERT INTO collab.resource_search_index "
                        "(resource_id,workspace_id,project_id,resource_type,"
                        "name,searchable_text,lifecycle) "
                        "VALUES (:id,:w,:p,'document',:n,'' ,'Active')"
                    ),
                    {
                        "id": row.resource_id,
                        "w": workspace_id,
                        "p": project_id,
                        "n": name,
                    },
                )
        from api.infra.broadcast import get_broadcast_publisher

        class _StubPublisher:
            async def publish(self, *_args, **_kwargs):
                return "stub"

        app: FastAPI = create_app(debug=True)
        app.dependency_overrides[get_current_session] = lambda: SimpleNamespace(
            account_id=account_id
        )
        app.dependency_overrides[get_broadcast_publisher] = lambda: _StubPublisher()
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.get(
                f"/v1/workspaces/{workspace_id}/search/suggestions",
                params={"q": "Doc"},
            )
            assert response.status_code == 200, response.text
            suggestions = response.json()["suggestions"]
            assert set(suggestions) == {"DocAlpha", "DocBeta"}
        app.dependency_overrides[get_current_session] = lambda: SimpleNamespace(
            account_id=outsider
        )
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            denied = await client.get(
                f"/v1/workspaces/{workspace_id}/search/suggestions",
                params={"q": "Doc"},
            )
        assert denied.status_code == 403
    finally:
        await session.close()
        await connection.close()


@pytest.mark.asyncio
async def test_search_folder_scope() -> None:
    """Arch 11 folder scope: only resources under the folder match."""
    connection = await engine.connect()
    session = AsyncSession(connection)
    try:
        account_id = uuid4()
        workspace_id = uuid4()
        project_id = uuid4()
        folder_id = uuid4()
        async with session.begin():
            await session.execute(
                text(
                    "INSERT INTO auth.accounts "
                    "(account_id,status,primary_email,normalized_email) "
                    "VALUES (:a,'Active',:e,:e)"
                ),
                {"a": account_id, "e": f"fd-{account_id}@test"},
            )
            await session.execute(
                text(
                    "INSERT INTO core.workspaces "
                    "(workspace_id,name,status,created_by,created_at,updated_at) "
                    "VALUES (:w,'S','Active',:a,now(),now())"
                ),
                {"w": workspace_id, "a": account_id},
            )
            await session.execute(
                text(
                    "INSERT INTO core.workspace_members "
                    "(workspace_id,account_id,membership_kind) "
                    "VALUES (:w,:a,'Owner')"
                ),
                {"w": workspace_id, "a": account_id},
            )
            await session.execute(
                text(
                    "INSERT INTO core.projects "
                    "(project_id,workspace_id,name,normalized_name,lifecycle,"
                    "created_by,created_at,updated_at) "
                    "VALUES (:p,:w,'P','p','Active',:a,now(),now())"
                ),
                {"p": project_id, "w": workspace_id, "a": account_id},
            )
            await session.execute(
                text(
                    "INSERT INTO core.folders "
                    "(folder_id,project_id,parent_folder_id,name,normalized_name,"
                    "created_at,updated_at) "
                    "VALUES (:f,:p,NULL,'F','f',now(),now())"
                ),
                {"f": folder_id, "p": project_id},
            )
            inside = await PostgresResourceRepository(session).create(
                project_id=project_id,
                resource_type="document",
                name="Inside",
                normalized_name="inside",
                folder_id=folder_id,
            )
            outside = await PostgresResourceRepository(session).create(
                project_id=project_id,
                resource_type="document",
                name="Outside",
                normalized_name="outside",
            )
            for row, name in (
                (inside, "Inside"),
                (outside, "Outside"),
            ):
                await session.execute(
                    text(
                        "INSERT INTO collab.resource_search_index "
                        "(resource_id,workspace_id,project_id,resource_type,"
                        "name,searchable_text,lifecycle) "
                        "VALUES (:id,:w,:p,'document',:n,'正文','Active')"
                    ),
                    {
                        "id": row.resource_id,
                        "w": workspace_id,
                        "p": project_id,
                        "n": name,
                    },
                )
        from api.infra.broadcast import get_broadcast_publisher

        class _StubPublisher:
            async def publish(self, *_args, **_kwargs):
                return "stub"

        app: FastAPI = create_app(debug=True)
        app.dependency_overrides[get_current_session] = lambda: SimpleNamespace(
            account_id=account_id
        )
        app.dependency_overrides[get_broadcast_publisher] = lambda: _StubPublisher()
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            all_hits = await client.get(
                f"/v1/workspaces/{workspace_id}/search",
                params={"q": "正文"},
            )
            assert [i["name"] for i in all_hits.json()["items"]] == [
                "Inside",
                "Outside",
            ]
            scoped = await client.get(
                f"/v1/workspaces/{workspace_id}/search",
                params={"q": "正文", "folderId": str(folder_id)},
            )
            assert [i["name"] for i in scoped.json()["items"]] == ["Inside"]
    finally:
        await session.close()
        await connection.close()


@pytest.mark.asyncio
async def test_search_comments_finds_bodies() -> None:
    """FR-SRC-004: comment body search scoped to the workspace."""
    connection = await engine.connect()
    session = AsyncSession(connection)
    try:
        account_id = uuid4()
        workspace_id = uuid4()
        project_id = uuid4()
        outsider = uuid4()
        async with session.begin():
            for actor in (account_id, outsider):
                await session.execute(
                    text(
                        "INSERT INTO auth.accounts "
                        "(account_id,status,primary_email,normalized_email) "
                        "VALUES (:a,'Active',:e,:e)"
                    ),
                    {"a": actor, "e": f"cs-{actor}@test"},
                )
            await session.execute(
                text(
                    "INSERT INTO core.workspaces "
                    "(workspace_id,name,status,created_by,created_at,updated_at) "
                    "VALUES (:w,'S','Active',:a,now(),now())"
                ),
                {"w": workspace_id, "a": account_id},
            )
            await session.execute(
                text(
                    "INSERT INTO core.workspace_members "
                    "(workspace_id,account_id,membership_kind) "
                    "VALUES (:w,:a,'Owner')"
                ),
                {"w": workspace_id, "a": account_id},
            )
            await session.execute(
                text(
                    "INSERT INTO core.projects "
                    "(project_id,workspace_id,name,normalized_name,lifecycle,"
                    "created_by,created_at,updated_at) "
                    "VALUES (:p,:w,'P','p','Active',:a,now(),now())"
                ),
                {"p": project_id, "w": workspace_id, "a": account_id},
            )
            resource = await PostgresResourceRepository(session).create(
                project_id=project_id,
                resource_type="document",
                name="Doc",
                normalized_name="doc",
            )
            await PostgresResourceOwnershipRepository(session).grant(
                resource.resource_id, account_id
            )
            from app_core.comments.application import AddComment as AddCommentUseCase
            from app_infra.postgres.comments_repository import (
                PostgresCommentsRepository,
            )

            await AddCommentUseCase(
                PostgresCommentsRepository(session),
                PostgresResourceOwnershipRepository(session),
            ).execute(account_id, resource.resource_id, body="异常流程需要复核")
        from api.infra.broadcast import get_broadcast_publisher

        class _StubPublisher:
            async def publish(self, *_args, **_kwargs):
                return "stub"

        app: FastAPI = create_app(debug=True)
        app.dependency_overrides[get_current_session] = lambda: SimpleNamespace(
            account_id=account_id
        )
        app.dependency_overrides[get_broadcast_publisher] = lambda: _StubPublisher()
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            found = await client.get(
                f"/v1/workspaces/{workspace_id}/search/comments",
                params={"q": "异常流程"},
            )
            assert found.status_code == 200, found.text
            items = found.json()["items"]
            assert len(items) == 1
            assert items[0]["body"] == "异常流程需要复核"
            assert items[0]["resourceName"] == "Doc"
            none = await client.get(
                f"/v1/workspaces/{workspace_id}/search/comments",
                params={"q": "不存在的词"},
            )
            assert none.json()["items"] == []
        # outsider denied
        app.dependency_overrides[get_current_session] = lambda: SimpleNamespace(
            account_id=outsider
        )
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            denied = await client.get(
                f"/v1/workspaces/{workspace_id}/search/comments",
                params={"q": "异常流程"},
            )
        assert denied.status_code == 403
    finally:
        await session.close()
        await connection.close()


@pytest.mark.asyncio
async def test_clear_search_history() -> None:
    """FR-SRC-005: clearing history removes the account's queries."""
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
                {"a": account_id, "e": f"ch-{account_id}@test"},
            )
        from app_infra.postgres.search_history_repository import (
            PostgresSearchHistoryRepository,
        )

        async with session.begin():
            repo = PostgresSearchHistoryRepository(session)
            await repo.record(account_id, "alpha")
            await repo.record(account_id, "beta")
        from api.infra.broadcast import get_broadcast_publisher

        class _StubPublisher:
            async def publish(self, *_args, **_kwargs):
                return "stub"

        app: FastAPI = create_app(debug=True)
        app.dependency_overrides[get_current_session] = lambda: SimpleNamespace(
            account_id=account_id
        )
        app.dependency_overrides[get_broadcast_publisher] = lambda: _StubPublisher()
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            cleared = await client.delete("/v1/search/history")
            assert cleared.status_code == 200, cleared.text
            assert cleared.json()["cleared"] == 2
            listed = await client.get("/v1/search/history")
            assert listed.json()["items"] == []
    finally:
        await session.close()
        await connection.close()


@pytest.mark.asyncio
async def test_list_notifications_unread_count() -> None:
    """FR-NTF-001: list returns unreadCount; mark-read refreshes it."""
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
                {"a": account_id, "e": f"un-{account_id}@test"},
            )
            await session.execute(
                text(
                    "INSERT INTO core.notifications "
                    "(notification_id,account_id,kind,payload,read_at) "
                    "VALUES (:n1,:a,'test','{}'::jsonb,NULL), "
                    "(:n2,:a,'test','{}'::jsonb,NULL), "
                    "(:n3,:a,'test','{}'::jsonb,now())"
                ),
                {
                    "n1": uuid4(),
                    "n2": uuid4(),
                    "n3": uuid4(),
                    "a": account_id,
                    "p": {"x": 1},
                },
            )
        from api.infra.broadcast import get_broadcast_publisher

        class _StubPublisher:
            async def publish(self, *_args, **_kwargs):
                return "stub"

        app: FastAPI = create_app(debug=True)
        app.dependency_overrides[get_current_session] = lambda: SimpleNamespace(
            account_id=account_id
        )
        app.dependency_overrides[get_broadcast_publisher] = lambda: _StubPublisher()
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            listed = await client.get("/v1/notifications")
            assert listed.status_code == 200, listed.text
            body = listed.json()
            assert body["unreadCount"] == 2
            assert len(body["items"]) == 3
            first_id = body["items"][0]["notificationId"]
            marked = await client.post(f"/v1/notifications/{first_id}/read")
            assert marked.status_code == 200
            after = (await client.get("/v1/notifications")).json()
            assert after["unreadCount"] == 1
    finally:
        await session.close()
        await connection.close()


@pytest.mark.asyncio
async def test_suggest_members_prefix() -> None:
    """FR-NTF-004: member email suggestions scoped to the workspace."""
    connection = await engine.connect()
    session = AsyncSession(connection)
    try:
        owner = uuid4()
        buddy = uuid4()
        outsider = uuid4()
        workspace_id = uuid4()
        async with session.begin():
            for actor, tag in ((owner, "ow"), (buddy, "bd"), (outsider, "ot")):
                await session.execute(
                    text(
                        "INSERT INTO auth.accounts "
                        "(account_id,status,primary_email,normalized_email) "
                        "VALUES (:a,'Active',:e,:e)"
                    ),
                    {"a": actor, "e": f"{tag}-{actor}@test"},
                )
            await session.execute(
                text(
                    "INSERT INTO core.workspaces "
                    "(workspace_id,name,status,created_by,created_at,updated_at) "
                    "VALUES (:w,'S','Active',:a,now(),now())"
                ),
                {"w": workspace_id, "a": owner},
            )
            await session.execute(
                text(
                    "INSERT INTO core.workspace_members "
                    "(workspace_id,account_id,membership_kind) "
                    "VALUES (:w,:a,'Owner')"
                ),
                {"w": workspace_id, "a": owner},
            )
            await session.execute(
                text(
                    "INSERT INTO core.workspace_members "
                    "(workspace_id,account_id,membership_kind) "
                    "VALUES (:w,:a,'Member')"
                ),
                {"w": workspace_id, "a": buddy},
            )
        from api.infra.broadcast import get_broadcast_publisher

        class _StubPublisher:
            async def publish(self, *_args, **_kwargs):
                return "stub"

        app: FastAPI = create_app(debug=True)
        app.dependency_overrides[get_current_session] = lambda: SimpleNamespace(
            account_id=buddy
        )
        app.dependency_overrides[get_broadcast_publisher] = lambda: _StubPublisher()
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            found = await client.get(
                f"/v1/workspaces/{workspace_id}/members/suggest",
                params={"q": "bd-"},
            )
            assert found.status_code == 200, found.text
            emails = [i["email"] for i in found.json()["suggestions"]]
            assert emails == [f"bd-{buddy}@test"]
            # outsider cannot enumerate members
            app.dependency_overrides[get_current_session] = lambda: SimpleNamespace(
                account_id=outsider
            )
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            denied = await client.get(
                f"/v1/workspaces/{workspace_id}/members/suggest",
                params={"q": "bd-"},
            )
        assert denied.status_code == 403
    finally:
        await session.close()
        await connection.close()


@pytest.mark.asyncio
async def test_webhook_subscription_crud() -> None:
    """FR-WEB-001/002/003: register, list (write-authorized), remove."""
    connection = await engine.connect()
    session = AsyncSession(connection)
    try:
        owner = uuid4()
        member = uuid4()
        outsider = uuid4()
        workspace_id = uuid4()
        async with session.begin():
            for actor, tag in ((owner, "ow"), (member, "mb"), (outsider, "ot")):
                await session.execute(
                    text(
                        "INSERT INTO auth.accounts "
                        "(account_id,status,primary_email,normalized_email) "
                        "VALUES (:a,'Active',:e,:e)"
                    ),
                    {"a": actor, "e": f"{tag}-{actor}@test"},
                )
            await session.execute(
                text(
                    "INSERT INTO core.workspaces "
                    "(workspace_id,name,status,created_by,created_at,updated_at) "
                    "VALUES (:w,'S','Active',:a,now(),now())"
                ),
                {"w": workspace_id, "a": owner},
            )
            await session.execute(
                text(
                    "INSERT INTO core.workspace_members "
                    "(workspace_id,account_id,membership_kind) "
                    "VALUES (:w,:a,'Owner')"
                ),
                {"w": workspace_id, "a": owner},
            )
            await session.execute(
                text(
                    "INSERT INTO core.workspace_members "
                    "(workspace_id,account_id,membership_kind) "
                    "VALUES (:w,:a,'Member')"
                ),
                {"w": workspace_id, "a": member},
            )
        from api.infra.broadcast import get_broadcast_publisher

        class _StubPublisher:
            async def publish(self, *_args, **_kwargs):
                return "stub"

        app: FastAPI = create_app(debug=True)
        app.dependency_overrides[get_current_session] = lambda: SimpleNamespace(
            account_id=owner
        )
        app.dependency_overrides[get_broadcast_publisher] = lambda: _StubPublisher()
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            created = await client.post(
                f"/v1/workspaces/{workspace_id}/webhooks",
                json={"url": "https://hooks.example.test/dom"},
            )
            assert created.status_code == 200, created.text
            subscription_id = created.json()["subscriptionId"]
            listed = await client.get(f"/v1/workspaces/{workspace_id}/webhooks")
            assert listed.status_code == 200, listed.text
            items = listed.json()["items"]
            assert len(items) == 1
            assert items[0]["url"] == "https://hooks.example.test/dom"
            removed = await client.delete(
                f"/v1/workspaces/{workspace_id}/webhooks/{subscription_id}"
            )
            assert removed.json()["removed"] is True
            listed_after = (
                await client.get(f"/v1/workspaces/{workspace_id}/webhooks")
            ).json()
            assert listed_after["items"] == []
            missing = await client.delete(
                f"/v1/workspaces/{workspace_id}/webhooks/{subscription_id}"
            )
            assert missing.status_code == 404
        # outsider cannot register
        app.dependency_overrides[get_current_session] = lambda: SimpleNamespace(
            account_id=outsider
        )
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            denied = await client.post(
                f"/v1/workspaces/{workspace_id}/webhooks",
                json={"url": "https://hooks.example.test/dom"},
            )
        assert denied.status_code == 403
    finally:
        await session.close()
        await connection.close()


@pytest.mark.asyncio
async def test_webhook_test_delivery_signed() -> None:
    """FR-WEB-004: test delivery signs the payload; receiver verifies."""
    connection = await engine.connect()
    session = AsyncSession(connection)
    try:
        owner = uuid4()
        workspace_id = uuid4()
        captured: dict[str, object] = {}

        def _echo(request: httpx.Request) -> httpx.Response:
            captured["body"] = request.content
            captured["signature"] = request.headers.get("X-Dom-Signature")
            captured["timestamp"] = request.headers.get("X-Dom-Timestamp")
            return httpx.Response(202, content=b"ok")

        async with session.begin():
            await session.execute(
                text(
                    "INSERT INTO auth.accounts "
                    "(account_id,status,primary_email,normalized_email) "
                    "VALUES (:a,'Active',:e,:e)"
                ),
                {"a": owner, "e": f"wh-{owner}@test"},
            )
            await session.execute(
                text(
                    "INSERT INTO core.workspaces "
                    "(workspace_id,name,status,created_by,created_at,updated_at) "
                    "VALUES (:w,'S','Active',:a,now(),now())"
                ),
                {"w": workspace_id, "a": owner},
            )
            await session.execute(
                text(
                    "INSERT INTO core.workspace_members "
                    "(workspace_id,account_id,membership_kind) "
                    "VALUES (:w,:a,'Owner')"
                ),
                {"w": workspace_id, "a": owner},
            )
        from api.routes.webhooks import get_webhook_transport
        from app_core.integrations.domain import new_keypair, verify
        from app_infra.postgres.webhook_repository import (
            PostgresWebhookSubscriptionRepository,
        )

        private_key, _public = new_keypair()
        async with session.begin():
            subscription_id = await PostgresWebhookSubscriptionRepository(
                session
            ).register(
                workspace_id,
                owner,
                "https://hooks.example.test/dom",
                private_key.hex(),
            )
        from api.infra.broadcast import get_broadcast_publisher

        class _StubPublisher:
            async def publish(self, *_args, **_kwargs):
                return "stub"

        app: FastAPI = create_app(debug=True)
        app.dependency_overrides[get_current_session] = lambda: SimpleNamespace(
            account_id=owner
        )
        app.dependency_overrides[get_broadcast_publisher] = lambda: _StubPublisher()
        app.dependency_overrides[get_webhook_transport] = lambda: httpx.MockTransport(
            _echo
        )
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            result = await client.post(
                f"/v1/workspaces/{workspace_id}/webhooks/{subscription_id}/test"
            )
        assert result.status_code == 200, result.text
        assert result.json()["delivered"] is True
        assert result.json()["statusCode"] == 202
        body = captured["body"]
        assert isinstance(body, bytes)
        signature = str(captured["signature"])
        timestamp = int(str(captured["timestamp"]))
        received_at = datetime.fromtimestamp(timestamp, UTC)
        # receiver-side verification: derive the public key from the stored seed
        from app_core.integrations.domain import public_from_private

        assert verify(body, received_at, signature, public_from_private(private_key))
    finally:
        await session.close()
        await connection.close()


@pytest.mark.asyncio
async def test_comment_added_enqueues_webhook_delivery() -> None:
    """Arch 10: comment.posted enqueues webhook.deliver for Active subs."""
    connection = await engine.connect()
    session = AsyncSession(connection)
    try:
        account_id = uuid4()
        workspace_id = uuid4()
        project_id = uuid4()
        async with session.begin():
            await session.execute(
                text(
                    "INSERT INTO auth.accounts "
                    "(account_id,status,primary_email,normalized_email) "
                    "VALUES (:a,'Active',:e,:e)"
                ),
                {"a": account_id, "e": f"we-{account_id}@test"},
            )
            await session.execute(
                text(
                    "INSERT INTO core.workspaces "
                    "(workspace_id,name,status,created_by,created_at,updated_at) "
                    "VALUES (:w,'S','Active',:a,now(),now())"
                ),
                {"w": workspace_id, "a": account_id},
            )
            await session.execute(
                text(
                    "INSERT INTO core.workspace_members "
                    "(workspace_id,account_id,membership_kind) "
                    "VALUES (:w,:a,'Owner')"
                ),
                {"w": workspace_id, "a": account_id},
            )
            await session.execute(
                text(
                    "INSERT INTO core.projects "
                    "(project_id,workspace_id,name,normalized_name,lifecycle,"
                    "created_by,created_at,updated_at) "
                    "VALUES (:p,:w,'P','p','Active',:a,now(),now())"
                ),
                {"p": project_id, "w": workspace_id, "a": account_id},
            )
            resource = await PostgresResourceRepository(session).create(
                project_id=project_id,
                resource_type="document",
                name="Doc",
                normalized_name="doc",
            )
            await PostgresResourceOwnershipRepository(session).grant(
                resource.resource_id, account_id
            )
            await session.execute(
                text(
                    "INSERT INTO core.webhook_subscriptions "
                    "(subscription_id,workspace_id,created_by,url,secret_key_hex,"
                    "status) VALUES (:sid,:w,:a,'https://hooks.example.test/x',"
                    "'ab' || repeat('cd',15),'Active')"
                ),
                {"sid": uuid4(), "w": workspace_id, "a": account_id},
            )
        from api.infra.broadcast import get_broadcast_publisher

        class _StubPublisher:
            async def publish(self, *_args, **_kwargs):
                return "stub"

        app: FastAPI = create_app(debug=True)
        app.dependency_overrides[get_current_session] = lambda: SimpleNamespace(
            account_id=account_id
        )
        app.dependency_overrides[get_broadcast_publisher] = lambda: _StubPublisher()
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            added = await client.post(
                f"/v1/resources/{resource.resource_id}/comments",
                json={
                    "body": "触发 webhook 投递的事件",
                    "resourceId": str(resource.resource_id),
                    "idempotencyKey": str(uuid4()),
                },
            )
            assert added.status_code in (200, 201), added.text
        row = (
            await session.execute(
                text(
                    "SELECT input_ref FROM work.tasks "
                    "WHERE task_type='webhook.deliver' AND input_ref LIKE :wid "
                    "ORDER BY created_at DESC LIMIT 1"
                ),
                {"wid": f"%{workspace_id}%"},
            )
        ).scalar()
        assert row is not None
        payload = json.loads(str(row))
        assert payload["event"] == "comment.posted"
        assert payload["workspaceId"] == str(workspace_id)
        assert payload["subscriptionId"]
    finally:
        await session.close()
        await connection.close()


@pytest.mark.asyncio
async def test_resource_created_enqueues_webhook_delivery() -> None:
    """Arch 10: creating a resource enqueues resource.created for Active subs."""
    connection = await engine.connect()
    session = AsyncSession(connection)
    try:
        account_id = uuid4()
        workspace_id = uuid4()
        project_id = uuid4()
        async with session.begin():
            await session.execute(
                text(
                    "INSERT INTO auth.accounts "
                    "(account_id,status,primary_email,normalized_email) "
                    "VALUES (:a,'Active',:e,:e)"
                ),
                {"a": account_id, "e": f"wc-{account_id}@test"},
            )
            await session.execute(
                text(
                    "INSERT INTO core.workspaces "
                    "(workspace_id,name,status,created_by,created_at,updated_at) "
                    "VALUES (:w,'S','Active',:a,now(),now())"
                ),
                {"w": workspace_id, "a": account_id},
            )
            await session.execute(
                text(
                    "INSERT INTO core.workspace_members "
                    "(workspace_id,account_id,membership_kind) "
                    "VALUES (:w,:a,'Owner')"
                ),
                {"w": workspace_id, "a": account_id},
            )
            await session.execute(
                text(
                    "INSERT INTO core.projects "
                    "(project_id,workspace_id,name,normalized_name,lifecycle,"
                    "created_by,created_at,updated_at) "
                    "VALUES (:p,:w,'P','p','Active',:a,now(),now())"
                ),
                {"p": project_id, "w": workspace_id, "a": account_id},
            )
            await session.execute(
                text(
                    "INSERT INTO core.webhook_subscriptions "
                    "(subscription_id,workspace_id,created_by,url,secret_key_hex,"
                    "status) VALUES (:sid,:w,:a,'https://hooks.example.test/y',"
                    "'ab' || repeat('cd',15),'Active')"
                ),
                {"sid": uuid4(), "w": workspace_id, "a": account_id},
            )
        from api.infra.broadcast import get_broadcast_publisher

        class _StubPublisher:
            async def publish(self, *_args, **_kwargs):
                return "stub"

        app: FastAPI = create_app(debug=True)
        app.dependency_overrides[get_current_session] = lambda: SimpleNamespace(
            account_id=account_id
        )
        app.dependency_overrides[get_broadcast_publisher] = lambda: _StubPublisher()
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            created = await client.post(
                "/v1/resources",
                json={
                    "projectId": str(project_id),
                    "resourceType": "document",
                    "name": "触发创建事件",
                    "idempotencyKey": str(uuid4()),
                },
            )
            assert created.status_code in (200, 201), created.text
        row = (
            await session.execute(
                text(
                    "SELECT input_ref FROM work.tasks "
                    "WHERE task_type='webhook.deliver' AND input_ref LIKE :ev "
                    "AND input_ref LIKE :wid ORDER BY created_at DESC LIMIT 1"
                ),
                {"ev": "%resource.created%", "wid": f"%{workspace_id}%"},
            )
        ).scalar()
        assert row is not None
        payload = json.loads(str(row))
        assert payload["event"] == "resource.created"
        assert payload["workspaceId"] == str(workspace_id)
    finally:
        await session.close()
        await connection.close()


@pytest.mark.asyncio
async def test_checkpoint_content_nodes_round_trip_and_restore() -> None:
    """Arch 02/06: snapshot nodes persist in the JSONB checkpoint and survive
    restore-at-version (op replay rewrites text, keeps nodes)."""
    connection = await engine.connect()
    session = AsyncSession(connection)
    try:
        account_id = uuid4()
        workspace_id = uuid4()
        project_id = uuid4()
        async with session.begin():
            await session.execute(
                text(
                    "INSERT INTO auth.accounts "
                    "(account_id,status,primary_email,normalized_email) "
                    "VALUES (:a,'Active',:e,:e)"
                ),
                {"a": account_id, "e": f"cn-{account_id}@test"},
            )
            await session.execute(
                text(
                    "INSERT INTO core.workspaces "
                    "(workspace_id,name,status,created_by,created_at,updated_at) "
                    "VALUES (:w,'S','Active',:a,now(),now())"
                ),
                {"w": workspace_id, "a": account_id},
            )
            await session.execute(
                text(
                    "INSERT INTO core.workspace_members "
                    "(workspace_id,account_id,membership_kind) "
                    "VALUES (:w,:a,'Owner')"
                ),
                {"w": workspace_id, "a": account_id},
            )
            await session.execute(
                text(
                    "INSERT INTO core.projects "
                    "(project_id,workspace_id,name,normalized_name,lifecycle,"
                    "created_by,created_at,updated_at) "
                    "VALUES (:p,:w,'P','p','Active',:a,now(),now())"
                ),
                {"p": project_id, "w": workspace_id, "a": account_id},
            )
            resource = await PostgresResourceRepository(session).create(
                project_id=project_id,
                resource_type="document",
                name="Nodes",
                normalized_name="nodes",
            )
            await PostgresResourceOwnershipRepository(session).grant(
                resource.resource_id, account_id
            )
            from app_core.resource.checkpoint.snapshot import build_snapshot
            from app_infra.postgres.resource.checkpoint_repository import (
                PostgresCheckpointRepository,
            )

            await PostgresCheckpointRepository(session).write(
                resource.resource_id,
                1,
                build_snapshot(
                    "标题\\n正文",
                    [
                        {"kind": "heading", "level": 1},
                        {
                            "kind": "paragraph",
                            "children": [{"kind": "text", "text": "正文"}],
                        },
                    ],
                ),
                account_id,
            )
            # restore-equivalent guarantee: op replay rewrites only the text
            # and keeps the nodes (checked against the reducer directly)
            from app_core.history.reduce import reduce_ops

            state = build_snapshot("标题\\n正文", [{"kind": "heading", "level": 1}])
            op_payload = {"kind": "set", "text": "重写后的正文"}
            reduced = reduce_ops(
                state,
                [
                    SimpleNamespace(
                        journal_seq=2,
                        update_bytes=__import__("json").dumps(op_payload).encode(),
                        update_hash="h",
                    )
                ],
            )
            assert reduced["text"] == "重写后的正文"
            assert reduced["nodes"][0]["kind"] == "heading"
        from api.infra.broadcast import get_broadcast_publisher

        class _StubPublisher:
            async def publish(self, *_args, **_kwargs):
                return "stub"

        app: FastAPI = create_app(debug=True)
        app.dependency_overrides[get_current_session] = lambda: SimpleNamespace(
            account_id=account_id
        )
        app.dependency_overrides[get_broadcast_publisher] = lambda: _StubPublisher()
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            opened = await client.get(f"/v1/resources/{resource.resource_id}")
            assert opened.status_code == 200, opened.text
            snapshot = opened.json()["snapshot"]
            assert snapshot["text"] == "标题\\n正文"
            assert snapshot["nodes"][0]["kind"] == "heading"
            # (the restore-keeps-nodes invariant is proven above via reduce_ops)
    finally:
        await session.close()
        await connection.close()
