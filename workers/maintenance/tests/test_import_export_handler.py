from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any, cast
from uuid import UUID, uuid4

import pytest
from app_core.import_export.application import ExportResourceSnapshot, resource_ref
from app_core.import_export.domain import (
    EXPORT_TASK_TYPE,
    IMPORT_TASK_TYPE,
    ExportSession,
    ExportSessionStage,
    ImportSession,
    ImportSessionStage,
    export_session_ref,
    import_session_ref,
)
from app_core.import_export.ports import (
    ImportExportSessionRepository,
    TemporaryAssetStore,
)
from app_core.resource.application import ImportResource
from app_core.resource.domain import ResourceLifecycle
from app_core.resource.ports import ResourceRepository
from app_core.workspace.domain.project import ProjectExtendedLifecycle
from app_core.workspace.ports.project_repository import ProjectRepository

from workers.maintenance.task_handlers.import_export import (
    ExportResourceTaskHandler,
    ImportResourceTaskHandler,
)


class _Context:
    def __init__(self, task: Any) -> None:
        self.task = task
        self.checkpoints = 0
        self.progress: list[tuple[str | None, str | None, int | None, int | None]] = []

    async def checkpoint(self) -> None:
        self.checkpoints += 1

    async def report_progress(
        self, *, stage=None, message_code=None, current=None, total=None
    ) -> None:
        self.progress.append((stage, message_code, current, total))


class _Sessions:
    def __init__(
        self,
        import_session: ImportSession | None = None,
        export_session: ExportSession | None = None,
    ) -> None:
        self.import_session = import_session
        self.export_session = export_session
        self.saved_imports: list[ImportSession] = []
        self.saved_exports: list[ExportSession] = []

    async def get_import(self, import_id: UUID) -> ImportSession | None:
        if self.import_session and self.import_session.import_id == import_id:
            return self.import_session
        return None

    async def save_import(self, session: ImportSession) -> None:
        self.import_session = session
        self.saved_imports.append(session)

    async def get_export(self, export_id: UUID) -> ExportSession | None:
        if self.export_session and self.export_session.export_id == export_id:
            return self.export_session
        return None

    async def save_export(self, session: ExportSession) -> None:
        self.export_session = session
        self.saved_exports.append(session)


class _Assets:
    def __init__(self, source: bytes = b"{}") -> None:
        self.sources: dict[UUID, bytes] = {}
        self.results: dict[UUID, bytes] = {}
        self.source = source
        self.get_source_calls = 0

    async def get_import_source(self, asset_id: UUID) -> bytes:
        self.get_source_calls += 1
        return self.sources.get(asset_id, self.source)

    async def put_export_result(self, asset_id: UUID, data: bytes) -> None:
        self.results[asset_id] = data


class _Resources:
    def __init__(self, resource: Any) -> None:
        self.resource = resource

    async def get(self, resource_id: UUID) -> Any | None:
        if self.resource.resource_id != resource_id:
            return None
        return self.resource


class _Projects:
    def __init__(self, project: Any) -> None:
        self.project = project

    async def find_by_id(self, project_id: UUID) -> Any | None:
        if self.project.project_id != project_id:
            return None
        return self.project


class _Ownership:
    def __init__(self, allowed: bool = True) -> None:
        self.allowed = allowed
        self.calls: list[tuple[UUID, UUID, str]] = []

    async def authorize(
        self, actor_id: UUID, resource_id: UUID, operation: str
    ) -> bool:
        self.calls.append((actor_id, resource_id, operation))
        return self.allowed


class _Importer:
    def __init__(self) -> None:
        self.calls: list[tuple[UUID, UUID, dict[str, Any], UUID | None]] = []

    async def execute(
        self,
        actor_id: UUID,
        resource_id: UUID,
        document: dict[str, Any],
        *,
        operation_id: UUID | None = None,
    ) -> tuple[int, object]:
        self.calls.append((actor_id, resource_id, document, operation_id))
        return 11, object()


class _Snapshot:
    def __init__(self, document: dict[str, Any]) -> None:
        self.document = document
        self.calls: list[tuple[UUID, UUID]] = []

    async def execute(self, actor_id: UUID, resource_id: UUID) -> dict[str, Any]:
        self.calls.append((actor_id, resource_id))
        return dict(self.document)


def _scope() -> tuple[UUID, UUID, UUID, _Resources, _Projects]:
    actor_id = uuid4()
    resource_id = uuid4()
    project_id = uuid4()
    workspace_id = uuid4()
    resource = SimpleNamespace(
        resource_id=resource_id,
        project_id=project_id,
        lifecycle=ResourceLifecycle.ACTIVE,
    )
    project = SimpleNamespace(
        project_id=project_id,
        workspace_id=workspace_id,
        lifecycle=ProjectExtendedLifecycle.ACTIVE,
    )
    return actor_id, resource_id, workspace_id, _Resources(resource), _Projects(project)


def _import_session(actor_id: UUID, workspace_id: UUID, task_id: UUID) -> ImportSession:
    return ImportSession(
        import_id=uuid4(),
        workspace_id=workspace_id,
        project_id=uuid4(),
        stage=ImportSessionStage.CREATED,
        created_by=actor_id,
        source_asset_id=uuid4(),
        plan_ref="sha256:valid",
        result_ref=None,
        task_id=task_id,
        expires_at=datetime.now(UTC) + timedelta(days=1),
    )


def _task(
    task_type: str, actor_id: UUID, workspace_id: UUID, resource_id: UUID, ref: str
) -> Any:
    return SimpleNamespace(
        task_id=uuid4(),
        task_type=task_type,
        actor_account_id=actor_id,
        workspace_id=workspace_id,
        resource_id=resource_id,
        input_ref=ref,
    )


@pytest.mark.asyncio
async def test_import_handler_revalidates_and_persists_result_as_actor() -> None:
    actor_id, resource_id, workspace_id, resources, projects = _scope()
    task = _task(IMPORT_TASK_TYPE, actor_id, workspace_id, resource_id, "")
    session = _import_session(actor_id, workspace_id, task.task_id)
    assert session.source_asset_id is not None
    task.input_ref = import_session_ref(session.import_id)
    document = {"kind": "dom.resource.export.v1", "content": {"snapshot": {}}}
    assets = _Assets(json.dumps(document).encode())
    assets.sources[session.source_asset_id] = json.dumps(document).encode()
    sessions = _Sessions(import_session=session)
    ownership = _Ownership()
    importer = _Importer()
    context = _Context(task)
    handler = ImportResourceTaskHandler(
        cast(ImportExportSessionRepository, sessions),
        cast(TemporaryAssetStore, assets),
        cast(ResourceRepository, resources),
        cast(ProjectRepository, projects),
        ownership,
        cast(ImportResource, importer),
    )

    await handler.execute(context)

    assert importer.calls == [(actor_id, resource_id, document, session.import_id)]
    assert ownership.calls == [(actor_id, resource_id, "resource.update")]
    assert sessions.import_session is not None
    assert sessions.import_session.stage is ImportSessionStage.COMPLETED
    assert sessions.import_session.result_ref == f"resource:{resource_id}:journal:11"
    assert sessions.import_session.expires_at <= datetime.now(UTC) + timedelta(days=1)
    assert context.checkpoints == 1
    assert [item[0] for item in context.progress] == [
        "validating",
        "reading-source",
        "applying",
        "completed",
    ]


@pytest.mark.asyncio
async def test_import_handler_stops_when_permission_was_revoked() -> None:
    actor_id, resource_id, workspace_id, resources, projects = _scope()
    task = _task(IMPORT_TASK_TYPE, actor_id, workspace_id, resource_id, "")
    session = _import_session(actor_id, workspace_id, task.task_id)
    task.input_ref = import_session_ref(session.import_id)
    assets = _Assets()
    importer = _Importer()
    ownership = _Ownership(allowed=False)
    context = _Context(task)
    handler = ImportResourceTaskHandler(
        cast(ImportExportSessionRepository, _Sessions(import_session=session)),
        cast(TemporaryAssetStore, assets),
        cast(ResourceRepository, resources),
        cast(ProjectRepository, projects),
        ownership,
        cast(ImportResource, importer),
    )

    with pytest.raises(PermissionError, match="no longer has resource.update"):
        await handler.execute(context)

    assert ownership.calls == [(actor_id, resource_id, "resource.update")]
    assert assets.get_source_calls == 0
    assert importer.calls == []


@pytest.mark.asyncio
async def test_export_handler_persists_result_and_progress() -> None:
    actor_id, resource_id, workspace_id, resources, projects = _scope()
    task_id = uuid4()
    export_id = uuid4()
    result_asset_id = uuid4()
    session = ExportSession(
        export_id=export_id,
        workspace_id=workspace_id,
        source_ref=resource_ref(resource_id),
        format="dom.resource.export.v1",
        stage=ExportSessionStage.CREATED,
        created_by=actor_id,
        result_asset_id=result_asset_id,
        task_id=task_id,
        expires_at=datetime.now(UTC) + timedelta(days=1),
    )
    task = _task(
        EXPORT_TASK_TYPE,
        actor_id,
        workspace_id,
        resource_id,
        export_session_ref(export_id),
    )
    task.task_id = task_id
    assets = _Assets()
    sessions = _Sessions(export_session=session)
    ownership = _Ownership()
    snapshot = _Snapshot(
        {
            "kind": "dom.resource.export.v1",
            "schemaVersion": "1.0.0",
            "resource": {"resourceId": str(resource_id)},
        }
    )
    context = _Context(task)
    handler = ExportResourceTaskHandler(
        cast(ImportExportSessionRepository, sessions),
        cast(TemporaryAssetStore, assets),
        cast(ResourceRepository, resources),
        cast(ProjectRepository, projects),
        ownership,
        cast(ExportResourceSnapshot, snapshot),
    )

    await handler.execute(context)

    payload = assets.results[result_asset_id]
    document = json.loads(payload)
    assert document["kind"] == "dom.resource.export.v1"
    assert document["exportedAt"]
    assert sessions.export_session is not None
    assert sessions.export_session.stage is ExportSessionStage.READY
    assert sessions.export_session.expires_at <= datetime.now(UTC) + timedelta(hours=24)
    assert ownership.calls == [(actor_id, resource_id, "resource.read")]
    assert snapshot.calls == [(actor_id, resource_id)]
    assert context.checkpoints == 1
    assert [item[0] for item in context.progress] == [
        "preparing",
        "snapshotting",
        "writing-result",
        "completed",
    ]


@pytest.mark.asyncio
async def test_export_handler_rechecks_project_lifecycle() -> None:
    actor_id, resource_id, workspace_id, resources, projects = _scope()
    projects.project.lifecycle = ProjectExtendedLifecycle.ARCHIVED
    export_id = uuid4()
    task = _task(
        EXPORT_TASK_TYPE,
        actor_id,
        workspace_id,
        resource_id,
        export_session_ref(export_id),
    )
    session = ExportSession(
        export_id=export_id,
        workspace_id=workspace_id,
        source_ref=resource_ref(resource_id),
        format="dom.resource.export.v1",
        stage=ExportSessionStage.CREATED,
        created_by=actor_id,
        result_asset_id=uuid4(),
        task_id=task.task_id,
        expires_at=datetime.now(UTC) + timedelta(days=1),
    )
    snapshot = _Snapshot({"kind": "dom.resource.export.v1"})
    handler = ExportResourceTaskHandler(
        cast(ImportExportSessionRepository, _Sessions(export_session=session)),
        cast(TemporaryAssetStore, _Assets()),
        cast(ResourceRepository, resources),
        cast(ProjectRepository, projects),
        _Ownership(),
        cast(ExportResourceSnapshot, snapshot),
    )

    with pytest.raises(ValueError, match="source project is not active"):
        await handler.execute(_Context(task))

    assert snapshot.calls == []
