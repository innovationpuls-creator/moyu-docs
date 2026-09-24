from __future__ import annotations

from typing import Protocol
from uuid import UUID

from app_core.workspace.domain.folder import Folder


class FolderRepository(Protocol):
    async def save(self, folder: Folder) -> None: ...

    async def find_by_id(self, folder_id: UUID) -> Folder | None: ...

    async def list_by_project(self, project_id: UUID) -> list[Folder]: ...

    async def list_name_reservations(
        self, project_id: UUID, parent_folder_id: UUID | None
    ) -> list[Folder]: ...

    async def get_ancestors(self, folder_id: UUID) -> list[Folder]: ...

    async def list_descendant_ids(self, folder_id: UUID) -> set[UUID]: ...
