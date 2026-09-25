from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from app_core.import_export.domain import (
    DEFAULT_MAX_EXCHANGE_BYTES,
    EXPORT_TASK_TYPE,
    IMPORT_TASK_TYPE,
    ExportSession,
    ExportSessionStage,
    ImportExportConflictError,
    ImportExportExpiredError,
    ImportExportNotFoundError,
    ImportExportPayloadTooLargeError,
    ImportExportPermissionDeniedError,
    ImportSession,
    ImportSessionStage,
    export_session_ref,
    import_session_ref,
    parse_export_session_ref,
)
from app_core.import_export.ports import (
    ImportExportSessionRepository,
    ResourceExportSnapshotRepository,
    TemporaryAssetStore,
)
from app_core.operations.task import CreateTask, TaskLike, TaskRepository
from app_core.resource.domain import ResourceLifecycle
from app_core.resource.ports import ReadOnlyResourceOwnershipPort, ResourceRepository
from app_core.workspace.domain.project import ProjectExtendedLifecycle
from app_core.workspace.ports.project_repository import ProjectRepository


class CreateImportResourceTask:
    def __init__(
        self,
        tasks: TaskRepository,
        sessions: ImportExportSessionRepository,
        assets: TemporaryAssetStore,
        resources: ResourceRepository,
        projects: ProjectRepository,
        ownership: ReadOnlyResourceOwnershipPort,
    ) -> None:
        self._tasks = tasks
        self._sessions = sessions
        self._assets = assets
        self._resources = resources
        self._projects = projects
        self._ownership = ownership

    async def execute(
        self,
        actor_id: UUID,
        resource_id: UUID,
        document: dict,
        idempotency_key: UUID,
        *,
        max_bytes: int = DEFAULT_MAX_EXCHANGE_BYTES,
    ) -> tuple[TaskLike, UUID]:
        if document.get("kind") != "dom.resource.export.v1":
            raise ValueError("IMPORT_DOCUMENT_INVALID")
        payload = json.dumps(
            document, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
        if len(payload) > max_bytes:
            raise ImportExportPayloadTooLargeError("IMPORT_PAYLOAD_TOO_LARGE")
        if not await self._ownership.authorize(
            actor_id, resource_id, "resource.update"
        ):
            raise ImportExportPermissionDeniedError("no resource.update permission")
        resource = await self._resources.get(resource_id)
        if resource is None:
            raise ImportExportNotFoundError("resource not found")
        if resource.lifecycle is not ResourceLifecycle.ACTIVE:
            raise ImportExportNotFoundError("resource is not active")
        project = await self._projects.find_by_id(resource.project_id)
        if project is None or project.lifecycle is not ProjectExtendedLifecycle.ACTIVE:
            raise ImportExportNotFoundError("target project is not active")

        fingerprint = f"sha256:{hashlib.sha256(payload).hexdigest()}"
        existing = await self._tasks.get_by_actor_idempotency_key(
            actor_id, idempotency_key
        )
        if existing is not None:
            return await self._existing_import(existing, resource_id, fingerprint)

        task_id = uuid4()
        import_id = uuid4()
        source_asset_id = uuid4()
        session = ImportSession(
            import_id=import_id,
            workspace_id=project.workspace_id,
            project_id=resource.project_id,
            stage=ImportSessionStage.CREATED,
            created_by=actor_id,
            source_asset_id=source_asset_id,
            plan_ref=fingerprint,
            result_ref=None,
            task_id=task_id,
            expires_at=datetime.now(UTC) + timedelta(days=7),
        )
        await self._assets.put_import_source(source_asset_id, payload)
        try:
            task = await CreateTask(self._tasks).execute(
                IMPORT_TASK_TYPE,
                task_id=task_id,
                input_ref=import_session_ref(import_id),
                actor_account_id=actor_id,
                workspace_id=project.workspace_id,
                resource_id=resource_id,
                idempotency_key=idempotency_key,
            )
            if task.task_id != task_id:
                await self._assets.delete_import_source(source_asset_id)
                return await self._existing_import(task, resource_id, fingerprint)
            await self._sessions.create_import(session)
        except BaseException:
            await self._assets.delete_import_source(source_asset_id)
            raise
        return task, import_id

    async def _existing_import(
        self, task: TaskLike, resource_id: UUID, fingerprint: str
    ) -> tuple[TaskLike, UUID]:
        if task.task_type != IMPORT_TASK_TYPE or task.resource_id != resource_id:
            raise ImportExportConflictError("IDEMPOTENCY_KEY_CONFLICT")
        session = await self._sessions.get_import_by_task(task.task_id)
        if session is None:
            raise RuntimeError("idempotent import task has no session")
        if session.created_by != task.actor_account_id:
            raise ImportExportConflictError("IDEMPOTENCY_KEY_CONFLICT")
        if session.plan_ref != fingerprint:
            raise ImportExportConflictError("IDEMPOTENCY_KEY_CONFLICT")
        if session.expires_at <= datetime.now(UTC):
            raise ImportExportExpiredError("import session has expired")
        return task, session.import_id


class CreateExportResourceTask:
    def __init__(
        self,
        tasks: TaskRepository,
        sessions: ImportExportSessionRepository,
        resources: ResourceRepository,
        projects: ProjectRepository,
        ownership: ReadOnlyResourceOwnershipPort,
    ) -> None:
        self._tasks = tasks
        self._sessions = sessions
        self._resources = resources
        self._projects = projects
        self._ownership = ownership

    async def execute(
        self,
        actor_id: UUID,
        resource_id: UUID,
        idempotency_key: UUID,
    ) -> tuple[TaskLike, UUID]:
        if not await self._ownership.authorize(actor_id, resource_id, "resource.read"):
            raise ImportExportPermissionDeniedError("no resource.read permission")
        resource = await self._resources.get(resource_id)
        if resource is None or resource.lifecycle is not ResourceLifecycle.ACTIVE:
            raise ImportExportNotFoundError("resource not found")
        project = await self._projects.find_by_id(resource.project_id)
        if project is None or project.lifecycle is not ProjectExtendedLifecycle.ACTIVE:
            raise ImportExportNotFoundError("project is not active")

        existing = await self._tasks.get_by_actor_idempotency_key(
            actor_id, idempotency_key
        )
        if existing is not None:
            return await self._existing_export(existing, resource_id)

        export_id = uuid4()
        result_asset_id = uuid4()
        task_id = uuid4()
        task = await CreateTask(self._tasks).execute(
            EXPORT_TASK_TYPE,
            task_id=task_id,
            input_ref=export_session_ref(export_id),
            actor_account_id=actor_id,
            workspace_id=project.workspace_id,
            resource_id=resource_id,
            idempotency_key=idempotency_key,
        )
        if task.task_id != task_id:
            return await self._existing_export(task, resource_id)
        session = ExportSession(
            export_id=export_id,
            workspace_id=project.workspace_id,
            source_ref=resource_ref(resource_id),
            format="dom.resource.export.v1",
            stage=ExportSessionStage.CREATED,
            created_by=actor_id,
            result_asset_id=result_asset_id,
            task_id=task_id,
            expires_at=datetime.now(UTC) + timedelta(days=7),
        )
        await self._sessions.create_export(session)
        return task, export_id

    async def _existing_export(
        self, task: TaskLike, resource_id: UUID
    ) -> tuple[TaskLike, UUID]:
        if task.task_type != EXPORT_TASK_TYPE or task.resource_id != resource_id:
            raise ImportExportConflictError("IDEMPOTENCY_KEY_CONFLICT")
        try:
            export_id = parse_export_session_ref(task.input_ref)
        except ValueError as exc:
            raise ImportExportConflictError("IDEMPOTENCY_KEY_CONFLICT") from exc
        session = await self._sessions.get_export_by_task(task.task_id)
        if (
            session is None
            or session.export_id != export_id
            or session.source_ref != resource_ref(resource_id)
            or session.created_by != task.actor_account_id
        ):
            raise ImportExportConflictError("IDEMPOTENCY_KEY_CONFLICT")
        return task, export_id


class GetImportSession:
    def __init__(self, sessions: ImportExportSessionRepository) -> None:
        self._sessions = sessions

    async def execute(self, import_id: UUID) -> ImportSession:
        session = await self._sessions.get_import(import_id)
        if session is None:
            raise ImportExportNotFoundError("import session not found")
        if session.expires_at <= datetime.now(UTC):
            raise ImportExportExpiredError("import session has expired")
        return session

    async def for_task(self, task_id: UUID) -> ImportSession:
        session = await self._sessions.get_import_by_task(task_id)
        if session is None:
            raise ImportExportNotFoundError("import session not found")
        if session.expires_at <= datetime.now(UTC):
            raise ImportExportExpiredError("import session has expired")
        return session


class SaveImportSession:
    def __init__(self, sessions: ImportExportSessionRepository) -> None:
        self._sessions = sessions

    async def execute(self, session: ImportSession) -> None:
        await self._sessions.save_import(session)


class CreateExportSession:
    def __init__(self, sessions: ImportExportSessionRepository) -> None:
        self._sessions = sessions

    async def execute(self, session: ExportSession) -> ExportSession:
        return await self._sessions.create_export(session)


class GetExportSession:
    def __init__(self, sessions: ImportExportSessionRepository) -> None:
        self._sessions = sessions

    async def execute(self, export_id: UUID) -> ExportSession:
        session = await self._sessions.get_export(export_id)
        if session is None:
            raise ImportExportNotFoundError("export session not found")
        if session.expires_at <= datetime.now(UTC):
            raise ImportExportExpiredError("export session has expired")
        return session


class SaveExportSession:
    def __init__(self, sessions: ImportExportSessionRepository) -> None:
        self._sessions = sessions

    async def execute(self, session: ExportSession) -> None:
        await self._sessions.save_export(session)


class ExportResourceSnapshot:
    """Authorize and materialize one stable Resource/export read view."""

    def __init__(
        self,
        snapshots: ResourceExportSnapshotRepository,
        ownership: ReadOnlyResourceOwnershipPort,
    ) -> None:
        self._snapshots = snapshots
        self._ownership = ownership

    async def execute(self, actor_id: UUID, resource_id: UUID) -> dict:
        if not await self._ownership.authorize(actor_id, resource_id, "resource.read"):
            raise ImportExportPermissionDeniedError("no resource.read permission")
        view = await self._snapshots.read(resource_id)
        if view is None:
            raise ImportExportNotFoundError("resource not found")
        resource, checkpoint = view
        if resource.lifecycle is not ResourceLifecycle.ACTIVE:
            raise ImportExportNotFoundError("resource is not active")
        return {
            "kind": "dom.resource.export.v1",
            "schemaVersion": "1.0.0",
            "resource": {
                "resourceId": str(resource.resource_id),
                "resourceType": resource.resource_type,
                "name": resource.name,
            },
            "content": {
                "snapshot": checkpoint.snapshot if checkpoint is not None else None,
                "journalSeq": checkpoint.base_journal_seq if checkpoint else 0,
            },
        }


class GetExportResult:
    def __init__(
        self,
        sessions: ImportExportSessionRepository,
        assets: TemporaryAssetStore,
        resources: ResourceRepository,
        ownership: ReadOnlyResourceOwnershipPort,
    ) -> None:
        self._sessions = sessions
        self._assets = assets
        self._resources = resources
        self._ownership = ownership

    async def execute(
        self, actor_id: UUID, resource_id: UUID, export_id: UUID
    ) -> bytes:
        session = await GetExportSession(self._sessions).execute(export_id)
        if session.source_ref != resource_ref(resource_id):
            raise ImportExportNotFoundError("export result not found")
        if session.stage is not ExportSessionStage.READY:
            raise ImportExportNotFoundError("export result is not ready")
        if session.result_asset_id is None:
            raise ImportExportNotFoundError("export result is not available")
        if not await self._ownership.authorize(actor_id, resource_id, "resource.read"):
            raise ImportExportPermissionDeniedError("no resource.read permission")
        resource = await self._resources.get(resource_id)
        if resource is None or resource.lifecycle is not ResourceLifecycle.ACTIVE:
            raise ImportExportNotFoundError("resource not found")
        return await self._assets.get_export_result(session.result_asset_id)


class ExpireImportExportSessions:
    """Delete expired source/result objects before deleting their session rows."""

    def __init__(
        self,
        sessions: ImportExportSessionRepository,
        assets: TemporaryAssetStore,
    ) -> None:
        self._sessions = sessions
        self._assets = assets

    async def execute(self, *, limit: int = 100) -> int:
        now = datetime.now(UTC)
        completed_imports = await self._sessions.completed_imports(limit=limit)
        cleaned = 0
        for session in completed_imports:
            if session.source_asset_id is None:
                continue
            await self._assets.delete_import_source(session.source_asset_id)
            await self._sessions.save_import(replace(session, source_asset_id=None))
            cleaned += 1

        imports = await self._sessions.expired_imports(now, limit=limit)
        exports = await self._sessions.expired_exports(now, limit=limit)
        for import_session in imports:
            if import_session.source_asset_id is not None:
                await self._assets.delete_import_source(import_session.source_asset_id)
            await self._sessions.delete_import(import_session.import_id)
            cleaned += 1
        for export_session in exports:
            if export_session.result_asset_id is not None:
                await self._assets.delete_export_result(export_session.result_asset_id)
            await self._sessions.delete_export(export_session.export_id)
            cleaned += 1
        return cleaned


def resource_ref(resource_id: UUID) -> str:
    return f"resource:{resource_id}"
