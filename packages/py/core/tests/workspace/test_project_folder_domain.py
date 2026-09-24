from __future__ import annotations

from uuid import UUID

import pytest
from app_core.workspace.domain.folder import (
    Folder,
    FolderExtendedLifecycle,
    FolderName,
)
from app_core.workspace.domain.lifecycle import LifecycleConflict
from app_core.workspace.domain.project import (
    Project,
    ProjectExtendedLifecycle,
    ProjectName,
)
from app_core.workspace.domain.tree import (
    FolderTreeConflict,
    effective_folder_lifecycle,
    validate_folder_parent,
)

PROJECT_ID = UUID("30000000-0000-0000-0000-000000000003")
OTHER_PROJECT_ID = UUID("40000000-0000-0000-0000-000000000004")
FOLDER_ID = UUID("50000000-0000-0000-0000-000000000005")
PARENT_ID = UUID("60000000-0000-0000-0000-000000000006")


def test_project_and_folder_names_reuse_workspace_name_rules():
    assert ProjectName("  Cafe\u0301 ").collision_key == "café"
    assert FolderName("Straße").collision_key == FolderName("STRASSE").collision_key
    with pytest.raises(ValueError):
        ProjectName(" \n ")
    with pytest.raises(ValueError):
        FolderName("bad\x00name")


def test_project_archive_and_trash_transitions_keep_project_identity():
    project = Project(PROJECT_ID, UUID(int=2), ProjectName("Plan"))
    archived = project.transition("archive")
    assert archived.project_id == project.project_id
    assert archived.lifecycle is ProjectExtendedLifecycle.ARCHIVED
    assert archived.is_read_only
    active = archived.transition("unarchive")
    assert active.lifecycle is ProjectExtendedLifecycle.ACTIVE
    assert active.transition("trash").lifecycle is ProjectExtendedLifecycle.TRASHED


def test_project_cannot_be_archived_twice():
    with pytest.raises(LifecycleConflict):
        Project(
            PROJECT_ID,
            UUID(int=2),
            ProjectName("Plan"),
            ProjectExtendedLifecycle.ARCHIVED,
        ).transition("archive")


def test_folder_root_and_same_project_parent_are_valid():
    root = Folder(FOLDER_ID, PROJECT_ID, None, FolderName("docs"))
    child = Folder(PARENT_ID, PROJECT_ID, root.folder_id, FolderName("api"))
    validate_folder_parent(root, None)
    validate_folder_parent(child, root)


def test_folder_parent_must_be_in_same_project():
    folder = Folder(FOLDER_ID, PROJECT_ID, None, FolderName("docs"))
    other_project_parent = Folder(PARENT_ID, OTHER_PROJECT_ID, None, FolderName("root"))
    with pytest.raises(FolderTreeConflict):
        validate_folder_parent(folder, other_project_parent)


def test_move_rejects_self_or_descendant_parent():
    with pytest.raises(FolderTreeConflict):
        validate_folder_parent(
            Folder(FOLDER_ID, PROJECT_ID, None, FolderName("docs")),
            Folder(FOLDER_ID, PROJECT_ID, None, FolderName("docs")),
            descendant_ids={FOLDER_ID},
        )


def test_trashed_ancestor_makes_descendants_unreachable_without_mutating_them():
    root = Folder(
        FOLDER_ID,
        PROJECT_ID,
        None,
        FolderName("docs"),
        FolderExtendedLifecycle.TRASHED,
    )
    child = Folder(PARENT_ID, PROJECT_ID, FOLDER_ID, FolderName("api"))

    assert (
        effective_folder_lifecycle(child, {root.folder_id: root})
        is FolderExtendedLifecycle.TRASHED
    )
    assert child.lifecycle is FolderExtendedLifecycle.ACTIVE
