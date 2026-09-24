from __future__ import annotations

import asyncio
import os
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest
import pytest_asyncio
from alembic import command
from alembic.config import Config
from app_core.common.exceptions import IdempotencyConflictError
from app_core.workspace.application.project_use_cases import Project
from app_core.workspace.domain.project import (
    ProjectExtendedLifecycle,
    ProjectName,
)
from app_infra.postgres.engine import engine
from app_infra.postgres.mutation_idempotency_repository import (
    PostgresMutationIdempotencyRepository,
)
from app_infra.postgres.test_database_guard import require_isolated_database
from sqlalchemy.ext.asyncio import AsyncSession

DATABASE_URL = "postgresql+psycopg://torch@localhost:5432/dom_workspace_lifecycle_test"


@pytest_asyncio.fixture(scope="module", autouse=True)
async def migrated_database() -> None:
    database_url = require_isolated_database(os.environ["DATABASE_URL"])
    assert database_url == DATABASE_URL
    config = Config(str(Path("migrations/postgres/alembic.ini")))
    config.set_main_option("sqlalchemy.url", database_url)
    command.upgrade(config, "head")


def _project(name: str) -> Project:
    now = datetime.now(UTC)
    return Project(
        project_id=uuid4(),
        workspace_id=uuid4(),
        name=ProjectName(name),
        lifecycle=ProjectExtendedLifecycle.ACTIVE,
        created_by=uuid4(),
        created_at=now,
        updated_at=now,
    )


async def _run_operation(
    key: str, fingerprint: str, name: str, executions: list[str]
) -> Project:
    connection = await engine.connect()
    session = AsyncSession(connection)

    async def operation() -> Project:
        executions.append(name)
        return _project(name)

    try:
        async with session.begin():
            repository = PostgresMutationIdempotencyRepository(session)
            return await repository.execute(key, fingerprint, operation)
    finally:
        await session.close()
        await connection.close()


@pytest.mark.asyncio
async def test_atomic_claim_serializes_same_key_requests() -> None:
    executions: list[str] = []
    key = f"mut-race-{uuid4()}"
    results = await asyncio.wait_for(
        asyncio.gather(
            _run_operation(key, "sha256:same", "A", executions),
            _run_operation(key, "sha256:same", "B", executions),
            return_exceptions=True,
        ),
        timeout=10,
    )
    executed = [item for item in results if not isinstance(item, BaseException)]
    # Exactly one callback executed; the losing request replays the stored
    # completed result, so every returned Project carries the winner's name.
    assert len(executions) == 1
    assert len(executed) == 2
    assert {item.name.display for item in executed} == set(executions)


@pytest.mark.asyncio
async def test_fingerprint_mismatch_after_completion_conflicts() -> None:
    key = f"mut-conflict-{uuid4()}"
    await _run_operation(key, "sha256:first", "First", [])
    with pytest.raises(IdempotencyConflictError):
        await _run_operation(key, "sha256:second", "Second", [])
