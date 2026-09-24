from __future__ import annotations

from enum import StrEnum

from app_core.common.exceptions import ConflictError


class WorkspaceLifecycle(StrEnum):
    ACTIVE = "Active"
    DELETION_PENDING = "DeletionPending"
    DELETED = "Deleted"


class LifecycleConflict(ConflictError):
    """Raised when a requested transition is not valid for the current state."""

    def __init__(self, message: str) -> None:
        super().__init__(message, "WORKSPACE_LIFECYCLE_CONFLICT")


class ProjectLifecycle(StrEnum):
    ACTIVE = "Active"
    ARCHIVED = "Archived"
    TRASHED = "Trashed"


class FolderLifecycle(StrEnum):
    ACTIVE = "Active"
    TRASHED = "Trashed"


def transition_project(current: ProjectLifecycle, action: str) -> ProjectLifecycle:
    """Return the next Project state for a valid metadata lifecycle transition."""
    transitions = {
        (ProjectLifecycle.ACTIVE, "archive"): ProjectLifecycle.ARCHIVED,
        (ProjectLifecycle.ARCHIVED, "unarchive"): ProjectLifecycle.ACTIVE,
        (ProjectLifecycle.ACTIVE, "trash"): ProjectLifecycle.TRASHED,
        (ProjectLifecycle.TRASHED, "restore"): ProjectLifecycle.ACTIVE,
    }
    try:
        return transitions[(current, action)]
    except (KeyError, TypeError) as error:
        state = getattr(current, "value", repr(current))
        raise LifecycleConflict(
            f"cannot {action!r} Project in {state} state"
        ) from error


def transition_folder(current: FolderLifecycle, action: str) -> FolderLifecycle:
    """Return the next Folder state for a valid metadata lifecycle transition."""
    transitions = {
        (FolderLifecycle.ACTIVE, "trash"): FolderLifecycle.TRASHED,
        (FolderLifecycle.TRASHED, "restore"): FolderLifecycle.ACTIVE,
    }
    try:
        return transitions[(current, action)]
    except (KeyError, TypeError) as error:
        state = getattr(current, "value", repr(current))
        raise LifecycleConflict(f"cannot {action!r} Folder in {state} state") from error
