from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import UTC, datetime
from enum import StrEnum
from uuid import UUID

from app_core.workspace.domain.lifecycle import (
    FolderLifecycle,
    LifecycleConflict,
    transition_folder,
)
from app_core.workspace.domain.name import WorkspaceName


class FolderName(WorkspaceName):
    """Validated Folder display name using Workspace collision rules."""


class FolderExtendedLifecycle(StrEnum):
    ACTIVE = "Active"
    TRASHED = "Trashed"
    DELETED = "Deleted"


@dataclass(frozen=True)
class Folder:
    folder_id: UUID
    project_id: UUID
    parent_folder_id: UUID | None
    name: FolderName
    lifecycle: FolderExtendedLifecycle = FolderExtendedLifecycle.ACTIVE
    created_at: datetime | None = None
    updated_at: datetime | None = None

    def renamed(self, name: str, *, at: datetime | None = None) -> Folder:
        self._require_active()
        return replace(self, name=FolderName(name), updated_at=at or datetime.now(UTC))

    def moved(
        self, parent_folder_id: UUID | None, *, at: datetime | None = None
    ) -> Folder:
        self._require_active()
        return replace(
            self,
            parent_folder_id=parent_folder_id,
            updated_at=at or datetime.now(UTC),
        )

    def transition(self, action: str, *, at: datetime | None = None) -> Folder:
        try:
            next_state = transition_folder(
                FolderLifecycle(self.lifecycle.value), action
            )
        except (ValueError, LifecycleConflict) as error:
            raise LifecycleConflict(str(error)) from error
        return replace(
            self,
            lifecycle=FolderExtendedLifecycle(next_state.value),
            updated_at=at or datetime.now(UTC),
        )

    def _require_active(self) -> None:
        if self.lifecycle is not FolderExtendedLifecycle.ACTIVE:
            raise LifecycleConflict(
                f"cannot modify Folder in {self.lifecycle.value} state"
            )
