from __future__ import annotations

import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol
from uuid import UUID

from app_core.import_export.application import (
    ExportResourceSnapshot,
    GetExportSession,
    GetImportSession,
    SaveExportSession,
    SaveImportSession,
    resource_ref,
)
from app_core.import_export.domain import (
    DEFAULT_MAX_EXCHANGE_BYTES,
    EXPORT_TASK_TYPE,
    IMPORT_TASK_TYPE,
    ExportSessionStage,
    ImportExportNotFoundError,
    ImportSessionStage,
    parse_export_session_ref,
    parse_import_session_ref,
)
from app_core.import_export.ports import (
    ImportExportSessionRepository,
    TemporaryAssetStore,
)
from app_core.resource.application import ImportResource
from app_core.resource.domain import ResourceLifecycle
from app_core.resource.ports import ReadOnlyResourceOwnershipPort, ResourceRepository
from app_core.workspace.domain.project import ProjectExtendedLifecycle
from app_core.workspace.ports.project_repository import ProjectRepository
from task_runtime.domain import RetryableTaskError


class _Task(Protocol):
    task_id: UUID
    actor_account_id: UUID | None
    workspace_id: UUID | None
    resource_id: UUID | None
    input_ref: str | None


class _Context(Protocol):
    task: _Task

    async def checkpoint(self) -> None: ...

    async def report_progress(
        self,
        *,
        stage: str | None = None,
        message_code: str | None = None,
        current: int | None = None,
        total: int | None = None,
    ) -> None: ...


class ImportResourceTaskHandler:
    def __init__(
        self,
        sessions: ImportExportSessionRepository,
        assets: TemporaryAssetStore,
        resources: ResourceRepository,
        projects: ProjectRepository,
        ownership: ReadOnlyResourceOwnershipPort,
        importer: ImportResource,
    ) -> None:
        self._sessions = sessions
        self._assets = assets
        self._resources = resources
        self._projects = projects
        self._ownership = ownership
        self._importer = importer

    async def execute(self, context: _Context) -> None:
        await context.report_progress(
            stage="validating",
            message_code="import.resource.validating",
            current=0,
            total=3,
        )
        task = context.task
        import_id = parse_import_session_ref(task.input_ref)
        resource_id = _require_resource(task, IMPORT_TASK_TYPE)
        actor_id = _require_actor(task)
        session = await GetImportSession(self._sessions).execute(import_id)
        if session.task_id is None or session.created_by != actor_id:
            raise PermissionError("import session actor does not match task actor")
        if session.workspace_id != task.workspace_id:
            raise ValueError("import session workspace does not match task")
        if session.source_asset_id is None:
            raise ImportExportNotFoundError("import source object is unavailable")
        if not await self._ownership.authorize(
            actor_id, resource_id, "resource.update"
        ):
            raise PermissionError("import actor no longer has resource.update")
        resource = await self._resources.get(resource_id)
        if resource is None:
            raise LookupError("import target resource no longer exists")
        if resource.lifecycle is not ResourceLifecycle.ACTIVE:
            raise ValueError("import target resource is not active")
        project = await self._projects.find_by_id(resource.project_id)
        if (
            project is None
            or project.workspace_id != session.workspace_id
            or project.lifecycle is not ProjectExtendedLifecycle.ACTIVE
        ):
            raise ValueError("import target project is not active")

        await context.report_progress(
            stage="reading-source",
            message_code="import.resource.reading_source",
            current=1,
            total=3,
        )
        payload = await _read_import_source(self._assets, session.source_asset_id)
        try:
            document: Any = json.loads(payload)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError("IMPORT_DOCUMENT_INVALID") from exc
        if not isinstance(document, dict):
            raise ValueError("IMPORT_DOCUMENT_INVALID")

        await context.report_progress(
            stage="applying",
            message_code="import.resource.applying",
            current=2,
            total=3,
        )
        seq, _receipt = await self._importer.execute(
            actor_id, resource_id, document, operation_id=import_id
        )
        await context.checkpoint()
        updated = replace(
            session,
            stage=ImportSessionStage.COMPLETED,
            result_ref=f"resource:{resource_id}:journal:{seq}",
            expires_at=datetime.now(UTC) + timedelta(days=1),
        )
        await SaveImportSession(self._sessions).execute(updated)
        await context.report_progress(
            stage="completed",
            message_code="import.resource.completed",
            current=3,
            total=3,
        )


class ExportResourceTaskHandler:
    def __init__(
        self,
        sessions: ImportExportSessionRepository,
        assets: TemporaryAssetStore,
        resources: ResourceRepository,
        projects: ProjectRepository,
        ownership: ReadOnlyResourceOwnershipPort,
        export_snapshot: ExportResourceSnapshot,
        *,
        max_bytes: int = DEFAULT_MAX_EXCHANGE_BYTES,
    ) -> None:
        self._sessions = sessions
        self._assets = assets
        self._resources = resources
        self._projects = projects
        self._ownership = ownership
        self._export_snapshot = export_snapshot
        self._max_bytes = max_bytes

    async def execute(self, context: _Context) -> None:
        await context.report_progress(
            stage="preparing",
            message_code="export.resource.preparing",
            current=0,
            total=3,
        )
        task = context.task
        export_id = parse_export_session_ref(task.input_ref)
        resource_id = _require_resource(task, EXPORT_TASK_TYPE)
        actor_id = _require_actor(task)
        session = await GetExportSession(self._sessions).execute(export_id)
        if session.created_by != actor_id or session.workspace_id != task.workspace_id:
            raise PermissionError("export session actor does not match task actor")
        if session.source_ref != resource_ref(resource_id):
            raise ValueError("export session source does not match task resource")
        if session.result_asset_id is None:
            raise ImportExportNotFoundError("export result object is unavailable")
        resource = await self._resources.get(resource_id)
        if resource is None or resource.lifecycle is not ResourceLifecycle.ACTIVE:
            raise LookupError("export source resource is not active")
        project = await self._projects.find_by_id(resource.project_id)
        if (
            project is None
            or project.workspace_id != session.workspace_id
            or project.lifecycle is not ProjectExtendedLifecycle.ACTIVE
        ):
            raise ValueError("export source project is not active")
        if not await self._ownership.authorize(actor_id, resource_id, "resource.read"):
            raise PermissionError("export actor no longer has resource.read")

        await context.report_progress(
            stage="snapshotting",
            message_code="export.resource.snapshotting",
            current=1,
            total=3,
        )
        document = await self._export_snapshot.execute(actor_id, resource_id)
        document["exportedAt"] = datetime.now(UTC).isoformat()
        result = json.dumps(
            document, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
        if len(result) > self._max_bytes:
            raise ValueError("EXPORT_RESULT_TOO_LARGE")

        await context.report_progress(
            stage="writing-result",
            message_code="export.resource.writing_result",
            current=2,
            total=3,
        )
        try:
            await self._assets.put_export_result(session.result_asset_id, result)
        except (OSError, TimeoutError) as exc:
            raise RetryableTaskError("EXPORT_TEMPORARY_STORAGE_UNAVAILABLE") from exc
        await context.checkpoint()
        await SaveExportSession(self._sessions).execute(
            replace(
                session,
                stage=ExportSessionStage.READY,
                expires_at=datetime.now(UTC) + timedelta(hours=24),
            )
        )
        await context.report_progress(
            stage="completed",
            message_code="export.resource.completed",
            current=3,
            total=3,
        )


def _require_resource(task: _Task, task_type: str) -> UUID:
    if task.resource_id is None:
        raise ValueError(f"{task_type} task has no Resource")
    return task.resource_id


def _require_actor(task: _Task) -> UUID:
    if task.actor_account_id is None:
        raise ValueError("Import / Export task has no initiating actor")
    return task.actor_account_id


async def _read_import_source(assets: TemporaryAssetStore, asset_id: UUID) -> bytes:
    try:
        return await assets.get_import_source(asset_id)
    except FileNotFoundError as exc:
        raise ImportExportNotFoundError("import source object is missing") from exc
    except (OSError, TimeoutError) as exc:
        raise RetryableTaskError("IMPORT_TEMPORARY_STORAGE_UNAVAILABLE") from exc
