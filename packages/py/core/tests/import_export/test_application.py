from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from app_core.import_export.application import (
    CreateExportResourceTask,
    CreateImportResourceTask,
)
from app_core.import_export.domain import (
    EXPORT_TASK_TYPE,
    IMPORT_TASK_TYPE,
    ExportSessionStage,
    ImportExportConflictError,
    ImportExportNotFoundError,
    ImportExportPayloadTooLargeError,
    ImportSessionStage,
    export_session_ref,
    import_session_ref,
)
from app_core.resource.domain import ResourceLifecycle
from app_core.workspace.domain.project import ProjectExtendedLifecycle


class _Tasks:
    def __init__(self) -> None:
        self.by_key: dict[tuple[UUID, UUID], object] = {}
        self.by_id: dict[UUID, object] = {}

    async def get_by_actor_idempotency_key(self, actor_id: UUID, key: UUID):
        return self.by_key.get((actor_id, key))

    async def create_idempotent(self, task):
        key = (task.actor_account_id, task.idempotency_key)
        existing = self.by_key.get(key)
        if existing is not None:
            return existing
        self.by_key[key] = task
        self.by_id[task.task_id] = task
        return task


class _Sessions:
    def __init__(self) -> None:
        self.imports = {}
        self.exports = {}
        self.imports_by_task = {}
        self.exports_by_task = {}

    async def create_import(self, session):
        self.imports[session.import_id] = session
        self.imports_by_task[session.task_id] = session
        return session

    async def get_import_by_task(self, task_id):
        return self.imports_by_task.get(task_id)

    async def create_export(self, session):
        self.exports[session.export_id] = session
        self.exports_by_task[session.task_id] = session
        return session

    async def get_export_by_task(self, task_id):
        return self.exports_by_task.get(task_id)


class _Assets:
    def __init__(self) -> None:
        self.import_sources: dict[UUID, bytes] = {}

    async def put_import_source(self, asset_id: UUID, data: bytes) -> None:
        self.import_sources[asset_id] = data

    async def delete_import_source(self, asset_id: UUID) -> None:
        self.import_sources.pop(asset_id, None)


class _Resources:
    def __init__(self, resource) -> None:
        self.resource = resource

    async def get(self, resource_id):
        if self.resource.resource_id != resource_id:
            return None
        return self.resource


class _Projects:
    def __init__(self, project) -> None:
        self.project = project

    async def find_by_id(self, project_id):
        if self.project.project_id != project_id:
            return None
        return self.project


class _Ownership:
    def __init__(self, allowed: bool = True) -> None:
        self.allowed = allowed
        self.calls = []

    async def authorize(self, actor_id, resource_id, operation):
        self.calls.append((actor_id, resource_id, operation))
        return self.allowed


def _scope():
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


@pytest.mark.asyncio
async def test_import_task_stages_source_and_reuses_idempotency_key() -> None:
    actor_id, resource_id, workspace_id, resources, projects = _scope()
    tasks = _Tasks()
    sessions = _Sessions()
    assets = _Assets()
    use_case = CreateImportResourceTask(
        tasks, sessions, assets, resources, projects, _Ownership()
    )
    key = uuid4()
    document = {"kind": "dom.resource.export.v1", "content": {"snapshot": {}}}

    task, import_id = await use_case.execute(actor_id, resource_id, document, key)
    replay, replay_id = await use_case.execute(actor_id, resource_id, document, key)

    session = sessions.imports[import_id]
    assert task.task_type == IMPORT_TASK_TYPE
    assert task.input_ref == import_session_ref(import_id)
    assert task.workspace_id == workspace_id
    assert task.actor_account_id == actor_id
    assert task.task_id == replay.task_id
    assert replay_id == import_id
    assert session.stage is ImportSessionStage.CREATED
    assert session.task_id == task.task_id
    assert len(assets.import_sources) == 1
    assert next(iter(assets.import_sources.values())) == (
        b'{"content":{"snapshot":{}},"kind":"dom.resource.export.v1"}'
    )


@pytest.mark.asyncio
async def test_import_task_rejects_idempotency_key_reuse_with_different_payload() -> (
    None
):
    actor_id, resource_id, _, resources, projects = _scope()
    use_case = CreateImportResourceTask(
        _tasks := _Tasks(), _Sessions(), _Assets(), resources, projects, _Ownership()
    )
    key = uuid4()
    await use_case.execute(
        actor_id,
        resource_id,
        {"kind": "dom.resource.export.v1", "content": {"snapshot": {}}},
        key,
    )

    with pytest.raises(ImportExportConflictError):
        await use_case.execute(
            actor_id,
            resource_id,
            {"kind": "dom.resource.export.v1", "content": {"snapshot": {"x": 1}}},
            key,
        )

    assert len(_tasks.by_id) == 1


@pytest.mark.asyncio
async def test_import_task_rejects_oversized_payload_before_staging() -> None:
    actor_id, resource_id, _, resources, projects = _scope()
    assets = _Assets()
    use_case = CreateImportResourceTask(
        _Tasks(), _Sessions(), assets, resources, projects, _Ownership()
    )

    with pytest.raises(ImportExportPayloadTooLargeError):
        await use_case.execute(
            actor_id,
            resource_id,
            {"kind": "dom.resource.export.v1", "content": {"snapshot": {}}},
            uuid4(),
            max_bytes=1,
        )

    assert assets.import_sources == {}


@pytest.mark.asyncio
async def test_export_task_persists_session_and_reuses_idempotency_key() -> None:
    actor_id, resource_id, workspace_id, resources, projects = _scope()
    tasks = _Tasks()
    sessions = _Sessions()
    use_case = CreateExportResourceTask(
        tasks, sessions, resources, projects, _Ownership()
    )
    key = uuid4()

    task, export_id = await use_case.execute(actor_id, resource_id, key)
    replay, replay_id = await use_case.execute(actor_id, resource_id, key)

    session = sessions.exports[export_id]
    assert task.task_type == EXPORT_TASK_TYPE
    assert task.input_ref == export_session_ref(export_id)
    assert task.workspace_id == workspace_id
    assert task.actor_account_id == actor_id
    assert task.task_id == replay.task_id
    assert replay_id == export_id
    assert session.stage is ExportSessionStage.CREATED
    assert session.created_by == actor_id
    assert session.task_id == task.task_id
    assert session.expires_at > datetime.now(UTC) + timedelta(days=6)


@pytest.mark.asyncio
async def test_export_task_rejects_inactive_project() -> None:
    actor_id, resource_id, _, resources, projects = _scope()
    projects.project.lifecycle = ProjectExtendedLifecycle.ARCHIVED
    tasks = _Tasks()
    use_case = CreateExportResourceTask(
        tasks, _Sessions(), resources, projects, _Ownership()
    )

    with pytest.raises(ImportExportNotFoundError, match="project is not active"):
        await use_case.execute(actor_id, resource_id, uuid4())

    assert tasks.by_id == {}
