from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from app_core.import_export.domain import (
    ExportSession,
    ExportSessionStage,
    ImportSession,
    ImportSessionStage,
)
from app_core.import_export.ports import (
    ImportExportSessionRepository,
    ResourceExportSnapshotRepository,
)
from app_core.resource.domain import Checkpoint, Resource, ResourceLifecycle
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


class PostgresImportExportSessionRepository(ImportExportSessionRepository):
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create_import(self, session: ImportSession) -> ImportSession:
        row = (
            (
                await self._session.execute(
                    text(
                        "INSERT INTO work.import_sessions "
                        "(import_id,workspace_id,project_id,stage,created_by,"
                        "source_asset_id,plan_ref,result_ref,task_id,expires_at) "
                        "VALUES (:import_id,:workspace_id,:project_id,:stage,"
                        ":created_by,"
                        ":source_asset_id,:plan_ref,:result_ref,:task_id,:expires_at) "
                        "RETURNING *"
                    ),
                    _import_params(session),
                )
            )
            .mappings()
            .one()
        )
        return _import_from_row(row)

    async def get_import(self, import_id: UUID) -> ImportSession | None:
        row = (
            (
                await self._session.execute(
                    text("SELECT * FROM work.import_sessions WHERE import_id=:id"),
                    {"id": import_id},
                )
            )
            .mappings()
            .one_or_none()
        )
        return _import_from_row(row) if row is not None else None

    async def get_import_by_task(self, task_id: UUID) -> ImportSession | None:
        row = (
            (
                await self._session.execute(
                    text("SELECT * FROM work.import_sessions WHERE task_id=:task_id"),
                    {"task_id": task_id},
                )
            )
            .mappings()
            .one_or_none()
        )
        return _import_from_row(row) if row is not None else None

    async def save_import(self, session: ImportSession) -> None:
        await self._session.execute(
            text(
                "UPDATE work.import_sessions SET stage=:stage,plan_ref=:plan_ref,"
                "result_ref=:result_ref,task_id=:task_id,"
                "source_asset_id=:source_asset_id,expires_at=:expires_at,"
                "updated_at=now() WHERE import_id=:import_id"
            ),
            _import_params(session),
        )

    async def expired_imports(
        self, now: datetime, *, limit: int
    ) -> list[ImportSession]:
        rows = (
            (
                await self._session.execute(
                    text(
                        "SELECT s.* FROM work.import_sessions AS s "
                        "LEFT JOIN work.tasks AS t ON t.task_id=s.task_id "
                        "WHERE s.expires_at<=:now AND (s.task_id IS NULL OR "
                        "t.state IN ('Succeeded','PartialSucceeded','Failed',"
                        "'Cancelled')) AND NOT EXISTS (SELECT 1 FROM work.tasks AS "
                        "active WHERE active.input_ref="
                        "'import-session://' || s.import_id::text AND active.state "
                        "NOT IN ('Succeeded','PartialSucceeded','Failed','Cancelled')) "
                        "ORDER BY s.expires_at,s.import_id LIMIT :limit"
                    ),
                    {"now": now, "limit": limit},
                )
            )
            .mappings()
            .all()
        )
        return [_import_from_row(row) for row in rows]

    async def completed_imports(self, *, limit: int) -> list[ImportSession]:
        rows = (
            (
                await self._session.execute(
                    text(
                        "SELECT * FROM work.import_sessions WHERE stage='Completed' "
                        "AND source_asset_id IS NOT NULL "
                        "AND NOT EXISTS (SELECT 1 FROM work.tasks AS active WHERE "
                        "active.input_ref='import-session://' || import_id::text "
                        "AND active.state NOT IN ('Succeeded','PartialSucceeded',"
                        "'Failed','Cancelled')) "
                        "ORDER BY updated_at,import_id LIMIT :limit"
                    ),
                    {"limit": limit},
                )
            )
            .mappings()
            .all()
        )
        return [_import_from_row(row) for row in rows]

    async def delete_import(self, import_id: UUID) -> None:
        await self._session.execute(
            text("DELETE FROM work.import_sessions WHERE import_id=:id"),
            {"id": import_id},
        )

    async def create_export(self, session: ExportSession) -> ExportSession:
        row = (
            (
                await self._session.execute(
                    text(
                        "INSERT INTO work.export_sessions "
                        "(export_id,workspace_id,source_ref,format,stage,created_by,"
                        "result_asset_id,task_id,expires_at) VALUES "
                        "(:export_id,:workspace_id,:source_ref,:format,:stage,:created_by,"
                        ":result_asset_id,:task_id,:expires_at) RETURNING *"
                    ),
                    _export_params(session),
                )
            )
            .mappings()
            .one()
        )
        return _export_from_row(row)

    async def get_export(self, export_id: UUID) -> ExportSession | None:
        row = (
            (
                await self._session.execute(
                    text("SELECT * FROM work.export_sessions WHERE export_id=:id"),
                    {"id": export_id},
                )
            )
            .mappings()
            .one_or_none()
        )
        return _export_from_row(row) if row is not None else None

    async def get_export_by_task(self, task_id: UUID) -> ExportSession | None:
        row = (
            (
                await self._session.execute(
                    text("SELECT * FROM work.export_sessions WHERE task_id=:task_id"),
                    {"task_id": task_id},
                )
            )
            .mappings()
            .one_or_none()
        )
        return _export_from_row(row) if row is not None else None

    async def save_export(self, session: ExportSession) -> None:
        await self._session.execute(
            text(
                "UPDATE work.export_sessions SET stage=:stage,"
                "result_asset_id=:result_asset_id,expires_at=:expires_at,"
                "updated_at=now() WHERE export_id=:export_id"
            ),
            _export_params(session),
        )

    async def expired_exports(
        self, now: datetime, *, limit: int
    ) -> list[ExportSession]:
        rows = (
            (
                await self._session.execute(
                    text(
                        "SELECT s.* FROM work.export_sessions AS s "
                        "JOIN work.tasks AS t ON t.task_id=s.task_id "
                        "WHERE s.expires_at<=:now AND t.state IN "
                        "('Succeeded','PartialSucceeded','Failed','Cancelled') "
                        "AND NOT EXISTS (SELECT 1 FROM work.tasks AS active WHERE "
                        "active.input_ref='export-session://' || s.export_id::text "
                        "AND active.state NOT IN ('Succeeded','PartialSucceeded',"
                        "'Failed','Cancelled')) "
                        "ORDER BY s.expires_at,s.export_id LIMIT :limit"
                    ),
                    {"now": now, "limit": limit},
                )
            )
            .mappings()
            .all()
        )
        return [_export_from_row(row) for row in rows]

    async def delete_export(self, export_id: UUID) -> None:
        await self._session.execute(
            text("DELETE FROM work.export_sessions WHERE export_id=:id"),
            {"id": export_id},
        )


class PostgresResourceExportSnapshotRepository(ResourceExportSnapshotRepository):
    """Read Resource metadata and its latest checkpoint in one SQL statement."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def read(
        self, resource_id: UUID
    ) -> tuple[Resource, Checkpoint | None] | None:
        row = (
            (
                await self._session.execute(
                    text(
                        "SELECT r.*, c.checkpoint_seq, c.base_journal_seq, c.snapshot, "
                        "c.created_at AS checkpoint_created_at "
                        "FROM core.resources AS r "
                        "LEFT JOIN LATERAL (SELECT checkpoint_seq,base_journal_seq,"
                        "snapshot,created_at FROM collab.resource_checkpoints "
                        "WHERE resource_id=r.resource_id ORDER BY checkpoint_seq DESC "
                        "LIMIT 1) AS c ON TRUE WHERE r.resource_id=:resource_id"
                    ),
                    {"resource_id": resource_id},
                )
            )
            .mappings()
            .one_or_none()
        )
        if row is None:
            return None
        resource = _resource_from_row(row)
        checkpoint = None
        if row["checkpoint_seq"] is not None:
            checkpoint = Checkpoint(
                resource_id=resource_id,
                checkpoint_seq=row["checkpoint_seq"],
                base_journal_seq=row["base_journal_seq"],
                snapshot=dict(row["snapshot"]),
                created_at=row["checkpoint_created_at"],
            )
        return resource, checkpoint


def _import_params(session: ImportSession) -> dict[str, Any]:
    return {
        "import_id": session.import_id,
        "workspace_id": session.workspace_id,
        "project_id": session.project_id,
        "stage": session.stage.value,
        "created_by": session.created_by,
        "source_asset_id": session.source_asset_id,
        "plan_ref": session.plan_ref,
        "result_ref": session.result_ref,
        "task_id": session.task_id,
        "expires_at": session.expires_at,
    }


def _export_params(session: ExportSession) -> dict[str, Any]:
    return {
        "export_id": session.export_id,
        "workspace_id": session.workspace_id,
        "source_ref": session.source_ref,
        "format": session.format,
        "stage": session.stage.value,
        "created_by": session.created_by,
        "result_asset_id": session.result_asset_id,
        "task_id": session.task_id,
        "expires_at": session.expires_at,
    }


def _import_from_row(row: Any) -> ImportSession:
    return ImportSession(
        import_id=row["import_id"],
        workspace_id=row["workspace_id"],
        project_id=row["project_id"],
        stage=ImportSessionStage(row["stage"]),
        created_by=row["created_by"],
        source_asset_id=row["source_asset_id"],
        plan_ref=row["plan_ref"],
        result_ref=row["result_ref"],
        task_id=row["task_id"],
        expires_at=row["expires_at"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def _export_from_row(row: Any) -> ExportSession:
    return ExportSession(
        export_id=row["export_id"],
        workspace_id=row["workspace_id"],
        source_ref=row["source_ref"],
        format=row["format"],
        stage=ExportSessionStage(row["stage"]),
        created_by=row["created_by"],
        result_asset_id=row["result_asset_id"],
        task_id=row["task_id"],
        expires_at=row["expires_at"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def _resource_from_row(row: Any) -> Resource:
    return Resource(
        resource_id=row["resource_id"],
        project_id=row["project_id"],
        folder_id=row["folder_id"],
        resource_type=row["resource_type"],
        name=row["name"],
        normalized_name=row["normalized_name"],
        lifecycle=ResourceLifecycle(row["lifecycle"]),
        schema_version=row["schema_version"],
        created_by=row["created_by"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        trashed_at=row["trashed_at"],
    )
