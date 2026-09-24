from __future__ import annotations

from typing import Protocol
from uuid import UUID

from app_core.workspace.domain.project import Project


class ProjectRepository(Protocol):
    async def save(self, project: Project) -> None: ...

    async def find_by_id(self, project_id: UUID) -> Project | None: ...

    async def list_by_workspace(self, workspace_id: UUID) -> list[Project]: ...

    async def list_name_reservations(self, workspace_id: UUID) -> list[Project]: ...
