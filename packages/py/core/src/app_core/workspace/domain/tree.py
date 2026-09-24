from __future__ import annotations

from collections.abc import Mapping, Set
from uuid import UUID

from app_core.common.exceptions import ConflictError
from app_core.workspace.domain.folder import Folder, FolderExtendedLifecycle
from app_core.workspace.domain.lifecycle import LifecycleConflict
from app_core.workspace.domain.project import Project, ProjectExtendedLifecycle


class FolderTreeConflict(ConflictError):
    """Raised when a Folder parent relationship would make the tree invalid."""

    def __init__(self, message: str, error_code: str) -> None:
        super().__init__(message, error_code)


def validate_folder_parent(
    folder: Folder,
    parent: Folder | None,
    *,
    descendant_ids: Set[UUID] = frozenset(),
) -> None:
    if parent is None:
        return
    if parent.project_id != folder.project_id:
        raise FolderTreeConflict(
            "parent Folder must belong to the same Project",
            "WORKSPACE_PARENT_INVALID",
        )
    if parent.folder_id == folder.folder_id or parent.folder_id in descendant_ids:
        raise FolderTreeConflict(
            "Folder cannot be moved under itself or a descendant",
            "FOLDER_CYCLE",
        )
    if parent.lifecycle is not FolderExtendedLifecycle.ACTIVE:
        raise LifecycleConflict("parent Folder must be Active")


def effective_folder_lifecycle(
    folder: Folder,
    ancestors: Mapping[UUID, Folder],
    project: Project | None = None,
) -> FolderExtendedLifecycle:
    if project is not None and project.lifecycle is not ProjectExtendedLifecycle.ACTIVE:
        return FolderExtendedLifecycle.TRASHED
    current = folder
    seen = {folder.folder_id}
    while current.parent_folder_id is not None:
        if current.parent_folder_id in seen:
            raise FolderTreeConflict("Folder ancestry contains a cycle", "FOLDER_CYCLE")
        seen.add(current.parent_folder_id)
        parent = ancestors.get(current.parent_folder_id)
        if parent is None:
            raise FolderTreeConflict("Folder ancestry is incomplete", "FOLDER_CYCLE")
        current = parent
        if current.lifecycle is not FolderExtendedLifecycle.ACTIVE:
            return current.lifecycle
    return folder.lifecycle


def project_tree_is_reachable(
    project: Project, folder: Folder, folder_map: Mapping[UUID, Folder]
) -> bool:
    return (
        folder.project_id == project.project_id
        and effective_folder_lifecycle(folder, folder_map, project)
        is FolderExtendedLifecycle.ACTIVE
    )
