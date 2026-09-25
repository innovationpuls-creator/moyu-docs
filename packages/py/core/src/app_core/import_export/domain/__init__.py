from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from uuid import UUID

IMPORT_TASK_TYPE = "import.resource"
EXPORT_TASK_TYPE = "export.resource"
DEFAULT_MAX_EXCHANGE_BYTES = 10 * 1024 * 1024


class ImportSessionStage(StrEnum):
    CREATED = "Created"
    IMPORTING = "Importing"
    COMPLETED = "Completed"
    EXPIRED = "Expired"


class ExportSessionStage(StrEnum):
    CREATED = "Created"
    EXPORTING = "Exporting"
    READY = "Ready"
    EXPIRED = "Expired"


class ImportExportError(Exception):
    """Base error for Import / Export session operations."""


class ImportExportNotFoundError(ImportExportError):
    pass


class ImportExportPermissionDeniedError(ImportExportError):
    pass


class ImportExportExpiredError(ImportExportError):
    pass


class ImportExportConflictError(ImportExportError):
    pass


class ImportExportPayloadTooLargeError(ImportExportError):
    pass


@dataclass(frozen=True)
class ImportSession:
    import_id: UUID
    workspace_id: UUID
    project_id: UUID | None
    stage: ImportSessionStage
    created_by: UUID
    source_asset_id: UUID | None
    plan_ref: str | None
    result_ref: str | None
    task_id: UUID | None
    expires_at: datetime
    created_at: datetime | None = None
    updated_at: datetime | None = None


@dataclass(frozen=True)
class ExportSession:
    export_id: UUID
    workspace_id: UUID
    source_ref: str
    format: str
    stage: ExportSessionStage
    created_by: UUID
    result_asset_id: UUID | None
    task_id: UUID
    expires_at: datetime
    created_at: datetime | None = None
    updated_at: datetime | None = None


def import_session_ref(import_id: UUID) -> str:
    return f"import-session://{import_id}"


def export_session_ref(export_id: UUID) -> str:
    return f"export-session://{export_id}"


def parse_import_session_ref(value: str | None) -> UUID:
    return _parse_session_ref(value, "import-session://")


def parse_export_session_ref(value: str | None) -> UUID:
    return _parse_session_ref(value, "export-session://")


def _parse_session_ref(value: str | None, prefix: str) -> UUID:
    if value is None or not value.startswith(prefix):
        raise ValueError("Import / Export task has no valid session reference")
    identity = value.removeprefix(prefix)
    try:
        parsed = UUID(identity)
    except ValueError as exc:
        raise ValueError("Import / Export task session reference is malformed") from exc
    if str(parsed) != identity:
        raise ValueError("Import / Export task session reference is not canonical")
    return parsed
