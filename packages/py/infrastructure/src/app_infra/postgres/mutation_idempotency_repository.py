from __future__ import annotations

import dataclasses
import json
from collections.abc import Awaitable, Callable
from datetime import datetime
from enum import StrEnum
from typing import Any, TypeVar, cast
from uuid import UUID

from app_core.common.exceptions import IdempotencyConflictError
from app_core.workspace.application.folder_use_cases import Folder
from app_core.workspace.application.project_use_cases import Project
from app_core.workspace.application.use_cases import Workspace
from app_core.workspace.domain.folder import (
    FolderExtendedLifecycle,
    FolderName,
)
from app_core.workspace.domain.lifecycle import WorkspaceLifecycle
from app_core.workspace.domain.name import WorkspaceName
from app_core.workspace.domain.project import (
    ProjectExtendedLifecycle,
    ProjectName,
)
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

T = TypeVar("T")

_KEY_PREFIX = "workspace:mutation:"


class PostgresMutationIdempotencyRepository:
    """Atomic, fingerprint-bound idempotency for Project/Folder/Workspace
    mutations using the caller-managed transaction.

    The operation callback runs exactly once for a winning claim; concurrent
    requests with the same key either replay the stored result (same
    fingerprint) or fail with ``IDEMPOTENCY_KEY_CONFLICT`` (different
    fingerprint or still in progress). Result serialization is explicit for the
    current domain entities; adding a new result type requires extending the
    serde map below rather than falling back to an ambiguous encoding.
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def execute(
        self,
        key: str,
        request_fingerprint: str,
        operation: Callable[[], Awaitable[T]],
    ) -> T:
        storage_key = f"{_KEY_PREFIX}{key}"
        claimed = await self._session.scalar(
            text(
                "INSERT INTO integration.idempotency_records "
                "(idempotency_key, response) VALUES (:key, :response) "
                "ON CONFLICT (idempotency_key) DO NOTHING "
                "RETURNING idempotency_key"
            ),
            {
                "key": storage_key,
                "response": json.dumps(
                    {
                        "request_fingerprint": request_fingerprint,
                        "phase": "in_progress",
                    },
                    separators=(",", ":"),
                ),
            },
        )
        if claimed is not None:
            result = await operation()
            type_tag, content = _encode_result(result)
            await self._session.execute(
                text(
                    "UPDATE integration.idempotency_records SET response=:response "
                    "WHERE idempotency_key=:key"
                ),
                {
                    "key": storage_key,
                    "response": json.dumps(
                        {
                            "request_fingerprint": request_fingerprint,
                            "phase": "completed",
                            "type": type_tag,
                            "content": content,
                        },
                        separators=(",", ":"),
                    ),
                },
            )
            return result

        stored = await self._session.scalar(
            text(
                "SELECT response FROM integration.idempotency_records "
                "WHERE idempotency_key=:key"
            ),
            {"key": storage_key},
        )
        if stored is None:
            raise IdempotencyConflictError(
                "Idempotency key is already in progress.", "IDEMPOTENCY_KEY_CONFLICT"
            )
        envelope = json.loads(stored)
        if envelope.get("request_fingerprint") != request_fingerprint:
            raise IdempotencyConflictError("IDEMPOTENCY_KEY_CONFLICT")
        if envelope.get("phase") != "completed":
            raise IdempotencyConflictError("IDEMPOTENCY_KEY_CONFLICT")
        return cast(T, _decode_result(envelope["type"], envelope["content"]))


def _json_default(value: object) -> str:
    if isinstance(value, StrEnum):
        return value.value
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    raise TypeError(f"Cannot serialize {type(value).__name__}")


def _encode_result(result: T) -> tuple[str, dict[str, object]]:
    type_tag = type(result).__name__
    if type_tag not in {"Project", "Folder", "Workspace"}:
        raise NotImplementedError(
            f"Mutation idempotency serde for {type_tag} is not implemented"
        )
    content = dataclasses.asdict(cast(Any, result))
    return type_tag, json.loads(json.dumps(content, default=_json_default))


def _decode_result(type_tag: str, content: dict[str, object]) -> object:
    if type_tag == "Project":
        _require_keys(type_tag, content, "project_id", "workspace_id", "name")
        name = _value_object_name(content["name"])
        return Project(
            project_id=UUID(str(content["project_id"])),
            workspace_id=UUID(str(content["workspace_id"])),
            name=ProjectName(name),
            lifecycle=ProjectExtendedLifecycle(str(content["lifecycle"])),
            created_by=_optional_uuid(content.get("created_by")),
            created_at=_optional_datetime(content.get("created_at")),
            updated_at=_optional_datetime(content.get("updated_at")),
        )
    if type_tag == "Folder":
        _require_keys(type_tag, content, "folder_id", "project_id", "name")
        name = _value_object_name(content["name"])
        return Folder(
            folder_id=UUID(str(content["folder_id"])),
            project_id=UUID(str(content["project_id"])),
            parent_folder_id=_optional_uuid(content.get("parent_folder_id")),
            name=FolderName(name),
            lifecycle=FolderExtendedLifecycle(str(content["lifecycle"])),
            created_at=_optional_datetime(content.get("created_at")),
            updated_at=_optional_datetime(content.get("updated_at")),
        )
    if type_tag == "Workspace":
        _require_keys(
            type_tag, content, "workspace_id", "name", "created_by", "lifecycle"
        )
        name = _value_object_name(content["name"])
        return Workspace(
            workspace_id=UUID(str(content["workspace_id"])),
            name=WorkspaceName(name),
            created_by=UUID(str(content["created_by"])),
            created_at=_required_datetime(content.get("created_at")),
            updated_at=_required_datetime(content.get("updated_at")),
            lifecycle=WorkspaceLifecycle(str(content["lifecycle"])),
        )
    raise NotImplementedError(
        f"Mutation idempotency serde for {type_tag} is not implemented"
    )


def _require_keys(type_tag: str, content: dict[str, object], *keys: str) -> None:
    missing = [key for key in keys if key not in content]
    if missing:
        raise ValueError(f"Stored {type_tag} idempotency content is missing {missing}")


def _value_object_name(value: object) -> str:
    if not isinstance(value, dict) or "display" not in value:
        raise ValueError("Stored name value object is invalid")
    return str(value["display"])


def _optional_uuid(value: object | None) -> UUID | None:
    return None if value is None else UUID(str(value))


def _optional_datetime(value: object | None) -> datetime | None:
    return None if value is None else datetime.fromisoformat(str(value))


def _required_datetime(value: object | None) -> datetime:
    if value is None:
        raise ValueError("Stored Workspace idempotency content lacks a timestamp")
    return datetime.fromisoformat(str(value))
