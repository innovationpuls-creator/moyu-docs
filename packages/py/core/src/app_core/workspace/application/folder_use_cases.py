from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from uuid import UUID, uuid4

from app_core.common.exceptions import ConflictError, NotFoundError
from app_core.permission.domain.workspace_membership import WorkspaceOperation
from app_core.permission.ports.workspace_access import WorkspaceAccessPort
from app_core.workspace.application.names import validated_folder_name
from app_core.workspace.application.project_use_cases import _fingerprint, _project
from app_core.workspace.domain.folder import Folder, FolderExtendedLifecycle, FolderName
from app_core.workspace.domain.lifecycle import LifecycleConflict
from app_core.workspace.domain.project import Project, ProjectExtendedLifecycle
from app_core.workspace.domain.tree import validate_folder_parent
from app_core.workspace.ports.events import LifecycleEvent, LifecycleEventPublisher
from app_core.workspace.ports.folder_repository import FolderRepository
from app_core.workspace.ports.mutation_idempotency import MutationIdempotencyPort
from app_core.workspace.ports.project_repository import ProjectRepository


class CreateFolder:
    def __init__(
        self,
        projects: ProjectRepository,
        folders: FolderRepository,
        access: WorkspaceAccessPort,
        id_factory: Callable[[], UUID] = uuid4,
        idempotency: MutationIdempotencyPort | None = None,
        events: LifecycleEventPublisher | None = None,
        now: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        if idempotency is None:
            raise ValueError("CreateFolder requires persistent idempotency")
        self._projects, self._folders, self._access = projects, folders, access
        self._id_factory, self._idempotency, self._now = id_factory, idempotency, now
        self._events = events

    async def execute(
        self,
        actor_id: UUID,
        project_id: UUID,
        parent_folder_id: UUID | None,
        name: str,
        *,
        idempotency_key: str,
    ) -> Folder:
        project = await _project(self._projects, project_id)
        folder_name = validated_folder_name(name)

        async def create() -> Folder:
            await self._access.authorize(
                actor_id,
                WorkspaceOperation.MANAGE,
                workspace_id=project.workspace_id,
            )
            _require_project_active(project)
            parent = (
                await self._folder(parent_folder_id)
                if parent_folder_id is not None
                else None
            )
            folder = Folder(
                self._id_factory(),
                project_id,
                parent_folder_id,
                folder_name,
                created_at=self._now(),
                updated_at=self._now(),
            )
            validate_folder_parent(folder, parent)
            siblings = await self._folders.list_name_reservations(
                project_id, parent_folder_id
            )
            _ensure_name_available(folder_name, siblings)
            await self._folders.save(folder)
            if self._events is not None:
                await self._events.publish(
                    LifecycleEvent.create(
                        "FolderCreated",
                        "event.workspace.folder-created.v1",
                        folder.folder_id,
                        {
                            "workspaceId": str(project.workspace_id),
                            "projectId": str(project.project_id),
                            "folderId": str(folder.folder_id),
                            "parentFolderId": (
                                str(folder.parent_folder_id)
                                if folder.parent_folder_id is not None
                                else None
                            ),
                            "name": folder.name.display,
                            "actorAccountId": str(actor_id),
                        },
                        occurred_at=folder.created_at,
                    )
                )
            return folder

        return await self._idempotency.execute(
            idempotency_key,
            _fingerprint(
                "CreateFolder",
                actor_id,
                {
                    "project_id": str(project_id),
                    "parent_folder_id": str(parent_folder_id),
                    "name": name,
                },
            ),
            create,
        )

    async def _folder(self, folder_id: UUID) -> Folder:
        folder = await self._folders.find_by_id(folder_id)
        if folder is None:
            raise NotFoundError("Folder not found", "FOLDER_NOT_FOUND")
        return folder


class RenameFolder:
    def __init__(
        self,
        projects: ProjectRepository,
        folders: FolderRepository,
        access: WorkspaceAccessPort,
        idempotency: MutationIdempotencyPort,
        *,
        events: LifecycleEventPublisher | None = None,
    ) -> None:
        self._projects, self._folders, self._access, self._idempotency = (
            projects,
            folders,
            access,
            idempotency,
        )
        self._events = events

    async def execute(
        self, actor_id: UUID, folder_id: UUID, name: str, *, idempotency_key: str
    ) -> Folder:
        folder = await _folder(self._folders, folder_id)
        project = await _project(self._projects, folder.project_id)
        folder_name = validated_folder_name(name)

        async def rename() -> Folder:
            await self._access.authorize(
                actor_id, WorkspaceOperation.MANAGE, workspace_id=project.workspace_id
            )
            _require_project_active(project)
            _require_folder_active(folder)
            siblings = await self._folders.list_name_reservations(
                folder.project_id, folder.parent_folder_id
            )
            _ensure_name_available(folder_name, siblings, excluding_id=folder_id)
            changed = folder.renamed(name)
            await self._folders.save(changed)
            if self._events is not None:
                await self._events.publish(
                    _folder_event("FolderRenamed", changed, project, actor_id)
                )
            return changed

        return await self._idempotency.execute(
            idempotency_key,
            _fingerprint(
                "RenameFolder",
                actor_id,
                {"folder_id": str(folder_id), "name": name},
            ),
            rename,
        )


class MoveFolder:
    def __init__(
        self,
        folders: FolderRepository,
        projects: ProjectRepository,
        access: WorkspaceAccessPort,
        idempotency: MutationIdempotencyPort,
        *,
        events: LifecycleEventPublisher | None = None,
        now: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._folders, self._projects, self._access, self._idempotency = (
            folders,
            projects,
            access,
            idempotency,
        )
        self._events = events
        self._now = now

    async def execute(
        self,
        actor_id: UUID,
        folder_id: UUID,
        destination_parent_folder_id: UUID | None,
        *,
        idempotency_key: str,
        descendant_ids: set[UUID] | None = None,
    ) -> Folder:
        folder = await _folder(self._folders, folder_id)
        project = await _project(self._projects, folder.project_id)

        async def move() -> Folder:
            await self._access.authorize(
                actor_id, WorkspaceOperation.MANAGE, workspace_id=project.workspace_id
            )
            _require_project_active(project)
            _require_folder_active(folder)
            parent = (
                await _folder(self._folders, destination_parent_folder_id)
                if destination_parent_folder_id is not None
                else None
            )
            descendants = descendant_ids
            if descendants is None:
                descendants = await self._folders.list_descendant_ids(folder_id)
            validate_folder_parent(folder, parent, descendant_ids=descendants)
            siblings = await self._folders.list_name_reservations(
                folder.project_id, destination_parent_folder_id
            )
            _ensure_name_available(folder.name, siblings, excluding_id=folder_id)
            changed = folder.moved(destination_parent_folder_id, at=self._now())
            await self._folders.save(changed)
            if self._events is not None:
                await self._events.publish(
                    _folder_event("FolderMoved", changed, project, actor_id)
                )
            return changed

        return await self._idempotency.execute(
            idempotency_key,
            _fingerprint(
                "MoveFolder",
                actor_id,
                {
                    "folder_id": str(folder_id),
                    "destination_parent_folder_id": str(destination_parent_folder_id),
                },
            ),
            move,
        )


class _FolderTransition:
    action: str
    operation: WorkspaceOperation

    def __init__(
        self,
        folders: FolderRepository,
        projects: ProjectRepository,
        access: WorkspaceAccessPort,
        idempotency: MutationIdempotencyPort,
        *,
        events: LifecycleEventPublisher | None = None,
        now: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._folders, self._projects, self._access, self._idempotency = (
            folders,
            projects,
            access,
            idempotency,
        )
        self._events = events
        self._now = now

    async def execute(
        self, actor_id: UUID, folder_id: UUID, *, idempotency_key: str
    ) -> Folder:
        folder = await _folder(self._folders, folder_id)
        project = await _project(self._projects, folder.project_id)

        async def transition() -> Folder:
            await self._access.authorize(
                actor_id, self.operation, workspace_id=project.workspace_id
            )
            changed = folder.transition(self.action, at=self._now())
            await self._folders.save(changed)
            if self._events is not None:
                event_type = {
                    "trash": "FolderTrashed",
                    "restore": "FolderRestored",
                }[self.action]
                await self._events.publish(
                    _folder_event(event_type, changed, project, actor_id)
                )
            return changed

        return await self._idempotency.execute(
            idempotency_key,
            _fingerprint(self.action, actor_id, {"folder_id": str(folder_id)}),
            transition,
        )


class TrashFolder(_FolderTransition):
    action, operation = "trash", WorkspaceOperation.TRASH


class RestoreFolder(_FolderTransition):
    action, operation = "restore", WorkspaceOperation.RESTORE

    async def execute(
        self, actor_id: UUID, folder_id: UUID, *, idempotency_key: str
    ) -> Folder:
        folder = await _folder(self._folders, folder_id)
        project = await _project(self._projects, folder.project_id)

        async def restore() -> Folder:
            await self._access.authorize(
                actor_id, self.operation, workspace_id=project.workspace_id
            )
            if project.lifecycle is not ProjectExtendedLifecycle.ACTIVE:
                raise LifecycleConflict("Project must be Active to restore a Folder")
            target_parent = folder.parent_folder_id
            parent = None
            if target_parent is not None:
                try:
                    parent = await _folder(self._folders, target_parent)
                except NotFoundError:
                    target_parent = None
                else:
                    if parent.lifecycle is not FolderExtendedLifecycle.ACTIVE:
                        target_parent, parent = None, None
            siblings = await self._folders.list_name_reservations(
                folder.project_id, target_parent
            )
            restored_name = _restored_name(folder.name, siblings, folder.folder_id)
            restored = folder.transition("restore", at=self._now())
            restored = restored.moved(target_parent, at=self._now()).renamed(
                restored_name.display, at=self._now()
            )
            validate_folder_parent(restored, parent)
            await self._folders.save(restored)
            if self._events is not None:
                await self._events.publish(
                    _folder_event("FolderRestored", restored, project, actor_id)
                )
            return restored

        return await self._idempotency.execute(
            idempotency_key,
            _fingerprint("restore", actor_id, {"folder_id": str(folder_id)}),
            restore,
        )


def _folder_event(
    event_type: str, folder: Folder, project: Project, actor_id: UUID
) -> LifecycleEvent:
    subject = {
        "FolderCreated": "event.workspace.folder-created.v1",
        "FolderRenamed": "event.workspace.folder-renamed.v1",
        "FolderMoved": "event.workspace.folder-moved.v1",
        "FolderTrashed": "event.workspace.folder-trashed.v1",
        "FolderRestored": "event.workspace.folder-restored.v1",
    }[event_type]
    return LifecycleEvent.create(
        event_type,
        subject,
        folder.folder_id,
        {
            "workspaceId": str(project.workspace_id),
            "projectId": str(project.project_id),
            "folderId": str(folder.folder_id),
            "parentFolderId": (
                str(folder.parent_folder_id)
                if folder.parent_folder_id is not None
                else None
            ),
            "name": folder.name.display,
            "actorAccountId": str(actor_id),
        },
        occurred_at=folder.updated_at,
    )


async def _folder(repository: FolderRepository, folder_id: UUID) -> Folder:
    folder = await repository.find_by_id(folder_id)
    if folder is None:
        raise NotFoundError("Folder not found", "FOLDER_NOT_FOUND")
    return folder


def _require_project_active(project: Project) -> None:
    if project.lifecycle is not ProjectExtendedLifecycle.ACTIVE:
        raise LifecycleConflict("Project is not writable in its current lifecycle")


def _require_folder_active(folder: Folder) -> None:
    if folder.lifecycle is not FolderExtendedLifecycle.ACTIVE:
        raise LifecycleConflict("Folder is not writable in its current lifecycle")


def _ensure_name_available(
    name: FolderName, rows: list[Folder], *, excluding_id: UUID | None = None
) -> None:
    if any(
        row.folder_id != excluding_id and row.name.collision_key == name.collision_key
        for row in rows
    ):
        raise ConflictError("Folder name already exists", "WORKSPACE_NAME_CONFLICT")


def _restored_name(
    original: FolderName, siblings: list[Folder], folder_id: UUID
) -> FolderName:
    if not any(
        sibling.folder_id != folder_id
        and sibling.name.collision_key == original.collision_key
        for sibling in siblings
    ):
        return original
    stem, dot, extension = original.display.rpartition(".")
    if not dot:
        stem, extension = original.display, ""
    suffix = f".{extension}" if dot else ""
    index = 1
    while True:
        candidate = FolderName(f"{stem} (restored {index}){suffix}")
        if not any(
            sibling.folder_id != folder_id
            and sibling.name.collision_key == candidate.collision_key
            for sibling in siblings
        ):
            return candidate
        index += 1
