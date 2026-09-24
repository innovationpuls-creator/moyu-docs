from __future__ import annotations

from app_core.common.exceptions import ValidationError
from app_core.workspace.domain.folder import FolderName
from app_core.workspace.domain.name import WorkspaceName
from app_core.workspace.domain.project import ProjectName

_NAME_INVALID = "WORKSPACE_NAME_INVALID"


def validated_workspace_name(value: str) -> WorkspaceName:
    try:
        return WorkspaceName(value)
    except ValueError as exc:
        raise ValidationError("Workspace name is invalid.", _NAME_INVALID) from exc


def validated_project_name(value: str) -> ProjectName:
    try:
        return ProjectName(value)
    except ValueError as exc:
        raise ValidationError("Workspace name is invalid.", _NAME_INVALID) from exc


def validated_folder_name(value: str) -> FolderName:
    try:
        return FolderName(value)
    except ValueError as exc:
        raise ValidationError("Workspace name is invalid.", _NAME_INVALID) from exc
