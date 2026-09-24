from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import UTC, datetime
from enum import StrEnum
from uuid import UUID

from app_core.workspace.domain.lifecycle import (
    LifecycleConflict,
    ProjectLifecycle,
    transition_project,
)
from app_core.workspace.domain.name import WorkspaceName


class ProjectName(WorkspaceName):
    """Validated Project display name using Workspace collision rules."""


class ProjectExtendedLifecycle(StrEnum):
    ACTIVE = "Active"
    ARCHIVED = "Archived"
    TRASHED = "Trashed"
    PURGING = "Purging"
    PURGED = "Purged"


@dataclass(frozen=True)
class Project:
    project_id: UUID
    workspace_id: UUID
    name: ProjectName
    lifecycle: ProjectExtendedLifecycle = ProjectExtendedLifecycle.ACTIVE
    created_by: UUID | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None

    @property
    def is_read_only(self) -> bool:
        return self.lifecycle is not ProjectExtendedLifecycle.ACTIVE

    def renamed(self, name: str, *, at: datetime | None = None) -> Project:
        self._require_active()
        return replace(self, name=ProjectName(name), updated_at=at or datetime.now(UTC))

    def transition(self, action: str, *, at: datetime | None = None) -> Project:
        try:
            current = ProjectLifecycle(self.lifecycle.value)
            next_state = transition_project(current, action)
        except (ValueError, LifecycleConflict) as error:
            raise LifecycleConflict(str(error)) from error
        return replace(
            self,
            lifecycle=ProjectExtendedLifecycle(next_state.value),
            updated_at=at or datetime.now(UTC),
        )

    def _require_active(self) -> None:
        if self.lifecycle is not ProjectExtendedLifecycle.ACTIVE:
            raise LifecycleConflict(
                f"cannot modify Project in {self.lifecycle.value} state"
            )
