import unicodedata

import pytest
from app_core.workspace.domain.lifecycle import (
    FolderLifecycle,
    LifecycleConflict,
    ProjectLifecycle,
    transition_folder,
    transition_project,
)
from app_core.workspace.domain.name import WorkspaceName


def test_workspace_name_preserves_display_and_builds_canonical_collision_key():
    name = WorkspaceName("  Cafe\u0301  ")

    assert name.display == "  Cafe\u0301  "
    assert name.collision_key == unicodedata.normalize("NFC", "Café").casefold()


def test_workspace_name_collision_key_uses_casefold():
    assert (
        WorkspaceName("Straße").collision_key == WorkspaceName("STRASSE").collision_key
    )


@pytest.mark.parametrize("value", ["", " \t\n "])
def test_workspace_name_rejects_blank(value: str) -> None:
    with pytest.raises(ValueError):
        WorkspaceName(value)


def test_workspace_name_rejects_more_than_120_unicode_codepoints():
    with pytest.raises(ValueError):
        WorkspaceName("界" * 121)


def test_workspace_name_accepts_120_unicode_codepoints():
    assert WorkspaceName("界" * 120).display == "界" * 120


@pytest.mark.parametrize("value", ["valid\x00name", "bad\x7fname"])
def test_workspace_name_rejects_control_characters(value: str) -> None:
    with pytest.raises(ValueError):
        WorkspaceName(value)


def test_project_archive_and_unarchive_transitions():
    assert transition_project(ProjectLifecycle.ACTIVE, "archive") is (
        ProjectLifecycle.ARCHIVED
    )
    assert transition_project(ProjectLifecycle.ARCHIVED, "unarchive") is (
        ProjectLifecycle.ACTIVE
    )


def test_project_trash_and_restore_transitions():
    assert transition_project(ProjectLifecycle.ACTIVE, "trash") is (
        ProjectLifecycle.TRASHED
    )
    assert transition_project(ProjectLifecycle.TRASHED, "restore") is (
        ProjectLifecycle.ACTIVE
    )


def test_archived_project_cannot_be_trashed_directly():
    with pytest.raises(LifecycleConflict):
        transition_project(ProjectLifecycle.ARCHIVED, "trash")


def test_folder_trash_and_restore_transitions():
    assert transition_folder(FolderLifecycle.ACTIVE, "trash") is FolderLifecycle.TRASHED
    assert (
        transition_folder(FolderLifecycle.TRASHED, "restore") is FolderLifecycle.ACTIVE
    )


def test_folder_does_not_support_archive():
    with pytest.raises(LifecycleConflict):
        transition_folder(FolderLifecycle.ACTIVE, "archive")


@pytest.mark.parametrize(
    ("transition", "current"),
    [
        (transition_project, "invalid"),
        (transition_folder, "invalid"),
    ],
)
def test_lifecycle_transition_rejects_malformed_state_type(transition, current):
    with pytest.raises(LifecycleConflict):
        transition(current, "archive")


@pytest.mark.parametrize("transition", [transition_project, transition_folder])
def test_lifecycle_transition_rejects_wrong_state_type(transition):
    with pytest.raises(LifecycleConflict):
        transition(object(), "archive")


@pytest.mark.parametrize(
    ("transition", "current"),
    [
        (transition_project, ProjectLifecycle.ACTIVE),
        (transition_folder, FolderLifecycle.ACTIVE),
    ],
)
def test_lifecycle_transition_rejects_unhashable_action(transition, current):
    with pytest.raises(LifecycleConflict):
        transition(current, [])
