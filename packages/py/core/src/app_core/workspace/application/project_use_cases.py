from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from uuid import UUID, uuid4

from app_core.common.exceptions import ConflictError, NotFoundError
from app_core.permission.domain.workspace_membership import WorkspaceOperation
from app_core.permission.ports.workspace_access import WorkspaceAccessPort
from app_core.workspace.application.names import (
    validated_project_name,
    validated_workspace_name,
)
from app_core.workspace.application.use_cases import Workspace
from app_core.workspace.domain.folder import (
    Folder,
    FolderExtendedLifecycle,
)
from app_core.workspace.domain.project import Project, ProjectName
from app_core.workspace.domain.tree import project_tree_is_reachable
from app_core.workspace.ports.events import LifecycleEvent, LifecycleEventPublisher
from app_core.workspace.ports.folder_repository import FolderRepository
from app_core.workspace.ports.mutation_idempotency import MutationIdempotencyPort
from app_core.workspace.ports.project_repository import ProjectRepository
from app_core.workspace.ports.workspace_repository import WorkspaceRepository


class RenameWorkspace:
    def __init__(
        self,
        workspaces: WorkspaceRepository,
        access: WorkspaceAccessPort,
        *,
        idempotency: MutationIdempotencyPort,
        now: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._workspaces = workspaces
        self._access = access
        self._idempotency = idempotency
        self._now = now

    async def execute(
        self, actor_id: UUID, workspace_id: UUID, name: str, *, idempotency_key: str
    ) -> Workspace:
        workspace = await self._workspaces.find_by_id(workspace_id)
        if workspace is None:
            raise NotFoundError("Workspace not found", "WORKSPACE_NOT_FOUND")
        workspace_name = validated_workspace_name(name)

        async def rename() -> Workspace:
            await self._access.authorize(
                actor_id, WorkspaceOperation.MANAGE, workspace_id=workspace_id
            )
            renamed = replace(workspace, name=workspace_name, updated_at=self._now())
            await self._workspaces.save(renamed)
            return renamed

        return await self._idempotency.execute(
            idempotency_key,
            _fingerprint(
                "RenameWorkspace",
                actor_id,
                {"workspace_id": str(workspace_id), "name": name},
            ),
            rename,
        )


def _fingerprint(action: str, actor_id: UUID, values: dict[str, object]) -> str:
    request = {"action": action, "actor_id": str(actor_id), **values}
    return hashlib.sha256(
        json.dumps(request, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


class CreateProject:
    def __init__(
        self,
        projects: ProjectRepository,
        access: WorkspaceAccessPort,
        *,
        idempotency: MutationIdempotencyPort,
        events: LifecycleEventPublisher | None = None,
        id_factory: Callable[[], UUID] = uuid4,
        now: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._projects, self._access, self._idempotency = projects, access, idempotency
        self._events = events
        self._id_factory, self._now = id_factory, now

    async def execute(
        self, actor_id: UUID, workspace_id: UUID, name: str, *, idempotency_key: str
    ) -> Project:
        project_name = validated_project_name(name)

        async def create() -> Project:
            await self._access.authorize(
                actor_id, WorkspaceOperation.MANAGE, workspace_id=workspace_id
            )
            reservations = await self._projects.list_name_reservations(workspace_id)
            _ensure_name_available(project_name, reservations)
            now = self._now()
            project = Project(
                self._id_factory(),
                workspace_id,
                project_name,
                created_by=actor_id,
                created_at=now,
                updated_at=now,
            )
            await self._projects.save(project)
            if self._events is not None:
                await self._events.publish(
                    LifecycleEvent.create(
                        "ProjectCreated",
                        "event.workspace.project-created.v1",
                        project.project_id,
                        {
                            "workspaceId": str(project.workspace_id),
                            "projectId": str(project.project_id),
                            "actorAccountId": str(actor_id),
                            "name": project.name.display,
                        },
                        occurred_at=project.created_at,
                    )
                )
            return project

        return await self._idempotency.execute(
            idempotency_key,
            _fingerprint(
                "CreateProject",
                actor_id,
                {"workspace_id": str(workspace_id), "name": name},
            ),
            create,
        )


class GetProjectTree:
    def __init__(
        self,
        workspaces: WorkspaceRepository,
        projects: ProjectRepository,
        folders: FolderRepository,
        access: WorkspaceAccessPort,
    ) -> None:
        self._workspaces, self._projects, self._folders, self._access = (
            workspaces,
            projects,
            folders,
            access,
        )

    async def execute(self, actor_id: UUID, project_id: UUID) -> ProjectTreeResult:
        project = await self._projects.find_by_id(project_id)
        if project is None:
            raise NotFoundError("Project not found", "PROJECT_NOT_FOUND")
        await self._access.authorize(
            actor_id, WorkspaceOperation.READ, workspace_id=project.workspace_id
        )
        workspace = await self._workspaces.find_by_id(project.workspace_id)
        if workspace is None:
            raise NotFoundError("Workspace not found", "WORKSPACE_NOT_FOUND")
        folders = await self._folders.list_by_project(project_id)
        folder_map = {folder.folder_id: folder for folder in folders}
        visible_folders = tuple(
            folder
            for folder in folders
            if folder.lifecycle is FolderExtendedLifecycle.ACTIVE
            and project_tree_is_reachable(project, folder, folder_map)
        )
        return ProjectTreeResult(workspace.workspace_id, project, visible_folders, None)


class RenameProject:
    def __init__(
        self,
        projects: ProjectRepository,
        access: WorkspaceAccessPort,
        *,
        idempotency: MutationIdempotencyPort,
    ) -> None:
        self._projects, self._access, self._idempotency = projects, access, idempotency

    async def execute(
        self, actor_id: UUID, project_id: UUID, name: str, *, idempotency_key: str
    ) -> Project:
        project = await _project(self._projects, project_id)

        async def rename() -> Project:
            await self._access.authorize(
                actor_id, WorkspaceOperation.MANAGE, workspace_id=project.workspace_id
            )
            project._require_active()
            rows = await self._projects.list_name_reservations(project.workspace_id)
            _ensure_name_available(
                validated_project_name(name), rows, excluding_id=project_id
            )
            changed = project.renamed(name)
            await self._projects.save(changed)
            return changed

        return await self._idempotency.execute(
            idempotency_key,
            _fingerprint(
                "RenameProject", actor_id, {"project_id": str(project_id), "name": name}
            ),
            rename,
        )


class _ProjectTransition:
    action: str
    operation: WorkspaceOperation

    def __init__(
        self,
        projects: ProjectRepository,
        access: WorkspaceAccessPort,
        idempotency: MutationIdempotencyPort,
        *,
        events: LifecycleEventPublisher | None = None,
    ) -> None:
        self._projects, self._access, self._idempotency = projects, access, idempotency
        self._events = events

    async def execute(
        self, actor_id: UUID, project_id: UUID, *, idempotency_key: str
    ) -> Project:
        project = await _project(self._projects, project_id)

        async def transition() -> Project:
            await self._access.authorize(
                actor_id, self.operation, workspace_id=project.workspace_id
            )
            changed = project.transition(self.action)
            await self._projects.save(changed)
            if self._events is not None:
                event_type = {
                    "archive": "ProjectArchived",
                    "unarchive": "ProjectUnarchived",
                    "trash": "ProjectTrashed",
                    "restore": "ProjectRestored",
                }[self.action]
                await self._events.publish(
                    LifecycleEvent.create(
                        event_type,
                        {
                            "archive": "event.workspace.project-archived.v1",
                            "unarchive": "event.workspace.project-unarchived.v1",
                            "trash": "event.workspace.project-trashed.v1",
                            "restore": "event.workspace.project-restored.v1",
                        }[self.action],
                        project.project_id,
                        {
                            "workspaceId": str(project.workspace_id),
                            "projectId": str(project.project_id),
                            "actorAccountId": str(actor_id),
                        },
                        occurred_at=changed.updated_at,
                    )
                )
            return changed

        return await self._idempotency.execute(
            idempotency_key,
            _fingerprint(self.action, actor_id, {"project_id": str(project_id)}),
            transition,
        )


class ArchiveProject(_ProjectTransition):
    action, operation = "archive", WorkspaceOperation.MANAGE


class UnarchiveProject(_ProjectTransition):
    action, operation = "unarchive", WorkspaceOperation.MANAGE


class TrashProject(_ProjectTransition):
    action, operation = "trash", WorkspaceOperation.TRASH


class RestoreProject(_ProjectTransition):
    action, operation = "restore", WorkspaceOperation.RESTORE


@dataclass(frozen=True)
class ProjectTreeResult:
    workspace_id: UUID
    project: Project
    folders: tuple[Folder, ...]
    next_cursor: str | None


async def _project(repository: ProjectRepository, project_id: UUID) -> Project:
    project = await repository.find_by_id(project_id)
    if project is None:
        raise NotFoundError("Project not found", "PROJECT_NOT_FOUND")
    return project


def _ensure_name_available(
    name: ProjectName, rows: list[Project], *, excluding_id: UUID | None = None
) -> None:
    if any(
        row.project_id != excluding_id and row.name.collision_key == name.collision_key
        for row in rows
    ):
        raise ConflictError("Project name already exists", "WORKSPACE_NAME_CONFLICT")
