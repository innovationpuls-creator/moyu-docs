from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any, cast
from uuid import uuid4

import pytest
from app_core.common.exceptions import IdempotencyConflictError
from app_core.workspace.application.folder_use_cases import Folder
from app_core.workspace.application.project_use_cases import Project
from app_core.workspace.domain.folder import FolderExtendedLifecycle, FolderName
from app_core.workspace.domain.name import WorkspaceName
from app_core.workspace.domain.project import (
    ProjectExtendedLifecycle,
    ProjectName,
)
from app_infra.postgres.mutation_idempotency_repository import (
    PostgresMutationIdempotencyRepository,
    _decode_result,
    _encode_result,
)
from sqlalchemy.ext.asyncio import AsyncSession

PROJECT = Project(
    project_id=uuid4(),
    workspace_id=uuid4(),
    name=ProjectName("Roadmap"),
    lifecycle=ProjectExtendedLifecycle.ACTIVE,
    created_by=uuid4(),
    created_at=datetime(2026, 9, 24, tzinfo=UTC),
    updated_at=datetime(2026, 9, 24, tzinfo=UTC),
)

FOLDER = Folder(
    folder_id=uuid4(),
    project_id=uuid4(),
    parent_folder_id=None,
    name=FolderName("Docs"),
    lifecycle=FolderExtendedLifecycle.ACTIVE,
    created_at=datetime(2026, 9, 24, tzinfo=UTC),
    updated_at=datetime(2026, 9, 24, tzinfo=UTC),
)


class _Session:
    """Scripted AsyncSession. ``scalar_pops`` feeds every scalar() call in order."""

    def __init__(self, scalar_pops: list[Any]) -> None:
        self._pops = list(scalar_pops)
        self.calls: list[tuple[str, Mapping[str, Any]]] = []

    async def scalar(self, statement: Any, params: Mapping[str, Any]) -> Any:
        self.calls.append((str(statement), params))
        return self._pops.pop(0)

    async def execute(self, statement: Any, params: Mapping[str, Any]) -> Any:
        self.calls.append((str(statement), params))
        return None


def _repo(session: _Session) -> PostgresMutationIdempotencyRepository:
    return PostgresMutationIdempotencyRepository(cast(AsyncSession, session))


async def _never() -> None:
    raise AssertionError("operation must not run on replay paths")


def _completed_envelope(fingerprint: str, result: object) -> str:
    type_tag, content = _encode_result(result)
    return json.dumps(
        {
            "request_fingerprint": fingerprint,
            "phase": "completed",
            "type": type_tag,
            "content": content,
        },
        separators=(",", ":"),
    )


def test_serde_roundtrip_project_and_folder() -> None:
    assert _decode_result("Project", _encode_result(PROJECT)[1]) == PROJECT
    assert _decode_result("Folder", _encode_result(FOLDER)[1]) == FOLDER


def test_serde_rejects_unsupported_type() -> None:
    with pytest.raises(NotImplementedError):
        _encode_result(WorkspaceName("x"))


@pytest.mark.asyncio
async def test_claim_winner_runs_operation_once_and_stores_completed_envelope() -> None:
    storage_key = "workspace:mutation:create-1"
    operations: list[int] = []
    session = _Session(scalar_pops=[storage_key])
    repository = _repo(session)

    async def operation() -> Project:
        operations.append(1)
        return PROJECT

    assert await repository.execute("create-1", "sha256:fp", operation) == PROJECT
    assert operations == [1]
    update_statement, update_params = session.calls[-1]
    assert "UPDATE integration.idempotency_records" in update_statement
    envelope = json.loads(update_params["response"])
    assert envelope["phase"] == "completed"
    assert envelope["request_fingerprint"] == "sha256:fp"


@pytest.mark.asyncio
async def test_replay_same_fingerprint_returns_stored_result() -> None:
    stored = _completed_envelope("sha256:fp", PROJECT)
    # Claim fails (key already exists) -> replay reads the stored envelope.
    session = _Session(scalar_pops=[None, stored])
    repository = _repo(session)
    operations: list[int] = []

    async def operation() -> Project:
        operations.append(1)
        return PROJECT

    assert await repository.execute("create-2", "sha256:fp", operation) == PROJECT
    assert operations == []


@pytest.mark.asyncio
async def test_fingerprint_mismatch_raises_conflict() -> None:
    stored = _completed_envelope("sha256:other", PROJECT)
    session = _Session(scalar_pops=[None, stored])
    repository = _repo(session)

    with pytest.raises(IdempotencyConflictError):
        await repository.execute("create-3", "sha256:fp", _never)


@pytest.mark.asyncio
async def test_in_progress_envelope_raises_conflict() -> None:
    stored = json.dumps({"request_fingerprint": "sha256:fp", "phase": "in_progress"})
    session = _Session(scalar_pops=[None, stored])
    repository = _repo(session)

    with pytest.raises(IdempotencyConflictError):
        await repository.execute("create-4", "sha256:fp", _never)
