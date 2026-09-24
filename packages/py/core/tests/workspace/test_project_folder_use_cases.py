from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

import pytest
from app_core.common.exceptions import ConflictError
from app_core.permission.domain.workspace_membership import WorkspaceOperation
from app_core.workspace.application.folder_use_cases import (
    CreateFolder,
    MoveFolder,
    RestoreFolder,
    TrashFolder,
)
from app_core.workspace.application.project_use_cases import (
    ArchiveProject,
    CreateProject,
    GetProjectTree,
    RenameWorkspace,
    RestoreProject,
    TrashProject,
    UnarchiveProject,
)
from app_core.workspace.application.use_cases import Workspace
from app_core.workspace.domain.folder import (
    Folder,
    FolderExtendedLifecycle,
    FolderName,
)
from app_core.workspace.domain.name import WorkspaceName
from app_core.workspace.domain.project import (
    Project,
    ProjectExtendedLifecycle,
    ProjectName,
)
from app_core.workspace.domain.tree import FolderTreeConflict

ACTOR_ID = UUID("10000000-0000-0000-0000-000000000001")
WORKSPACE_ID = UUID("20000000-0000-0000-0000-000000000002")
PROJECT_ID = UUID("30000000-0000-0000-0000-000000000003")
FOLDER_ID = UUID("40000000-0000-0000-0000-000000000004")
PARENT_ID = UUID("50000000-0000-0000-0000-000000000005")


class Access:
    def __init__(self, *, deny: bool = False) -> None:
        self.calls: list[tuple[UUID, WorkspaceOperation, UUID]] = []
        self.deny = deny

    async def authorize(
        self,
        actor_id: UUID,
        operation: WorkspaceOperation,
        *,
        workspace_id: UUID,
        project_id: UUID | None = None,
    ) -> None:
        self.calls.append((actor_id, operation, workspace_id))
        if self.deny:
            raise PermissionError("denied")


class ProjectRepo:
    def __init__(self, project: Project | None = None) -> None:
        self.project = project
        self.saved: list[Project] = []

    async def save(self, project: Project) -> None:
        self.saved.append(project)
        self.project = project

    async def find_by_id(self, project_id: UUID) -> Project | None:
        if self.project and self.project.project_id == project_id:
            return self.project
        return None

    async def list_name_reservations(self, workspace_id: UUID) -> list[Project]:
        if self.project is not None:
            return [self.project, *self.saved]
        return self.saved

    async def find_by_workspace(self, workspace_id: UUID) -> list[Project]:
        return self.saved


class FolderRepo:
    def __init__(self, folders: list[Folder] | None = None) -> None:
        self.folders = {folder.folder_id: folder for folder in folders or []}
        self.saved: list[Folder] = []

    async def save(self, folder: Folder) -> None:
        self.folders[folder.folder_id] = folder
        self.saved.append(folder)

    async def find_by_id(self, folder_id: UUID) -> Folder | None:
        return self.folders.get(folder_id)

    async def list_name_reservations(
        self, project_id: UUID, parent_folder_id: UUID | None
    ) -> list[Folder]:
        return [
            folder
            for folder in self.folders.values()
            if folder.project_id == project_id
            and folder.parent_folder_id == parent_folder_id
        ]

    async def list_by_project(self, project_id: UUID) -> list[Folder]:
        return [
            folder
            for folder in self.folders.values()
            if folder.project_id == project_id
        ]

    async def get_ancestors(self, folder_id: UUID) -> list[Folder]:
        result = []
        current = self.folders.get(folder_id)
        while current and current.parent_folder_id is not None:
            current = self.folders.get(current.parent_folder_id)
            if current:
                result.append(current)
        return result

    async def list_descendant_ids(self, folder_id: UUID) -> set[UUID]:
        found: set[UUID] = set()
        pending = [folder_id]
        while pending:
            parent_id = pending.pop()
            children = [
                folder
                for folder in self.folders.values()
                if folder.parent_folder_id == parent_id
            ]
            found.update(folder.folder_id for folder in children)
            pending.extend(folder.folder_id for folder in children)
        return found


class Ids:
    def __init__(self, values: list[UUID]) -> None:
        self.values = iter(values)

    def __call__(self) -> UUID:
        return next(self.values)


class Idempotency:
    async def execute(self, key: str, fingerprint: str, operation):
        return await operation()


class WorkspaceRepo:
    def __init__(self) -> None:
        self.workspace = Workspace(
            WORKSPACE_ID,
            WorkspaceName("Initial"),
            ACTOR_ID,
            datetime(2026, 1, 1, tzinfo=UTC),
            datetime(2026, 1, 1, tzinfo=UTC),
        )

    async def find_by_id(self, workspace_id: UUID) -> Workspace | None:
        return self.workspace if workspace_id == WORKSPACE_ID else None

    async def save(self, workspace: Workspace) -> None:
        self.workspace = workspace


@pytest.mark.asyncio
async def test_create_project_authorizes_and_uses_existing_names_including_trashed():
    trashed = Project(
        PROJECT_ID, WORKSPACE_ID, ProjectName("Plan"), ProjectExtendedLifecycle.TRASHED
    )
    projects = ProjectRepo(trashed)
    access = Access()
    use_case = CreateProject(
        projects, access, id_factory=Ids([UUID(int=9)]), idempotency=Idempotency()
    )

    with pytest.raises(ConflictError, match="name already exists"):
        await use_case.execute(ACTOR_ID, WORKSPACE_ID, " plan ", idempotency_key="cp-1")

    assert access.calls == [(ACTOR_ID, WorkspaceOperation.MANAGE, WORKSPACE_ID)]
    assert len(projects.saved) == 0


@pytest.mark.asyncio
async def test_create_project_persists_project_after_authorization():
    projects = ProjectRepo()
    access = Access()
    use_case = CreateProject(
        projects,
        access,
        id_factory=Ids([PROJECT_ID]),
        idempotency=Idempotency(),
    )

    project = await use_case.execute(
        ACTOR_ID, WORKSPACE_ID, "计划", idempotency_key="cp-2"
    )

    assert project.name == ProjectName("计划")
    assert projects.saved == [project]
    assert access.calls == [(ACTOR_ID, WorkspaceOperation.MANAGE, WORKSPACE_ID)]


@pytest.mark.asyncio
async def test_rename_workspace_authorizes_and_preserves_workspace_identity():
    workspaces = WorkspaceRepo()
    use_case = RenameWorkspace(workspaces, Access(), idempotency=Idempotency())

    renamed = await use_case.execute(
        ACTOR_ID, WORKSPACE_ID, "Roadmap", idempotency_key="rw-1"
    )

    assert renamed.workspace_id == WORKSPACE_ID
    assert renamed.name == WorkspaceName("Roadmap")
    assert renamed.created_by == ACTOR_ID


@pytest.mark.asyncio
async def test_create_folder_saves_root_folder_with_no_parent():
    projects = ProjectRepo(Project(PROJECT_ID, WORKSPACE_ID, ProjectName("Plan")))
    folders = FolderRepo()
    use_case = CreateFolder(
        projects,
        folders,
        Access(),
        id_factory=Ids([FOLDER_ID]),
        idempotency=Idempotency(),
    )

    folder = await use_case.execute(
        ACTOR_ID, PROJECT_ID, None, "根目录", idempotency_key="cf-root"
    )

    assert folder.parent_folder_id is None
    assert folders.saved == [folder]


@pytest.mark.asyncio
async def test_create_project_permission_denial_precedes_name_lookup_and_save():
    class UnreadableProjects(ProjectRepo):
        async def list_name_reservations(self, workspace_id: UUID) -> list[Project]:
            raise AssertionError("must authorize before metadata lookup")

    projects = UnreadableProjects()
    use_case = CreateProject(projects, Access(deny=True), idempotency=Idempotency())

    with pytest.raises(PermissionError, match="denied"):
        await use_case.execute(ACTOR_ID, WORKSPACE_ID, "Plan", idempotency_key="deny")

    assert projects.saved == []


@pytest.mark.asyncio
async def test_project_transitions_authorize_and_preserve_descendant_state():
    project = Project(PROJECT_ID, WORKSPACE_ID, ProjectName("Plan"))
    projects = ProjectRepo(project)
    access = Access()
    await ArchiveProject(projects, access, Idempotency()).execute(
        ACTOR_ID, PROJECT_ID, idempotency_key="pa"
    )
    assert projects.project.lifecycle is ProjectExtendedLifecycle.ARCHIVED
    await UnarchiveProject(projects, access, Idempotency()).execute(
        ACTOR_ID, PROJECT_ID, idempotency_key="pu"
    )
    await TrashProject(projects, access, Idempotency()).execute(
        ACTOR_ID, PROJECT_ID, idempotency_key="pt"
    )
    await RestoreProject(projects, access, Idempotency()).execute(
        ACTOR_ID, PROJECT_ID, idempotency_key="pr"
    )
    assert projects.project.lifecycle is ProjectExtendedLifecycle.ACTIVE


@pytest.mark.asyncio
async def test_get_project_tree_authorizes_read_and_returns_metadata_only():
    project = Project(PROJECT_ID, WORKSPACE_ID, ProjectName("Plan"))
    folder = Folder(FOLDER_ID, PROJECT_ID, None, FolderName("docs"))
    access = Access()
    result = await GetProjectTree(
        WorkspaceRepo(), ProjectRepo(project), FolderRepo([folder]), access
    ).execute(ACTOR_ID, PROJECT_ID)
    assert result.project is project
    assert result.folders == (folder,)
    assert access.calls == [(ACTOR_ID, WorkspaceOperation.READ, WORKSPACE_ID)]


@pytest.mark.asyncio
async def test_create_folder_validates_parent_and_name_reservations_before_saving():
    parent = Folder(PARENT_ID, PROJECT_ID, None, FolderName("docs"))
    existing = Folder(
        FOLDER_ID,
        PROJECT_ID,
        PARENT_ID,
        FolderName("api"),
        FolderExtendedLifecycle.TRASHED,
    )
    folders = FolderRepo([parent, existing])
    access = Access()
    use_case = CreateFolder(
        ProjectRepo(Project(PROJECT_ID, WORKSPACE_ID, ProjectName("Plan"))),
        folders,
        access,
        id_factory=Ids([UUID(int=10)]),
        idempotency=Idempotency(),
    )
    with pytest.raises(ConflictError, match="name already exists"):
        await use_case.execute(
            ACTOR_ID, PROJECT_ID, PARENT_ID, "API", idempotency_key="cf"
        )
    assert access.calls == [(ACTOR_ID, WorkspaceOperation.MANAGE, WORKSPACE_ID)]
    assert len(folders.saved) == 0


@pytest.mark.asyncio
async def test_move_folder_rejects_descendant_target_and_preserves_parent():
    parent = Folder(PARENT_ID, PROJECT_ID, None, FolderName("parent"))
    folder = Folder(FOLDER_ID, PROJECT_ID, PARENT_ID, FolderName("child"))
    folders = FolderRepo([parent, folder])
    access = Access()
    use_case = MoveFolder(
        folders,
        ProjectRepo(Project(PROJECT_ID, WORKSPACE_ID, ProjectName("Plan"))),
        access,
        Idempotency(),
    )
    with pytest.raises(FolderTreeConflict):
        await use_case.execute(
            ACTOR_ID,
            FOLDER_ID,
            PARENT_ID,
            descendant_ids={PARENT_ID},
            idempotency_key="mf",
        )
    assert folders.folders[FOLDER_ID].parent_folder_id == PARENT_ID
    assert folders.saved == []


@pytest.mark.asyncio
async def test_folder_restore_keeps_name_without_external_sibling_collision():
    folder = Folder(FOLDER_ID, PROJECT_ID, None, FolderName("notes"))
    folders = FolderRepo([folder])
    project = ProjectRepo(Project(PROJECT_ID, WORKSPACE_ID, ProjectName("Plan")))
    access = Access()

    await TrashFolder(folders, project, access, Idempotency()).execute(
        ACTOR_ID, FOLDER_ID, idempotency_key="tf-clean"
    )
    restored = await RestoreFolder(folders, project, access, Idempotency()).execute(
        ACTOR_ID, FOLDER_ID, idempotency_key="rf-clean"
    )

    assert restored.name.display == "notes"


@pytest.mark.asyncio
async def test_folder_restore_uses_safe_collision_suffix_and_keeps_descendants():
    folder = Folder(FOLDER_ID, PROJECT_ID, None, FolderName("readme.md"))
    child = Folder(PARENT_ID, PROJECT_ID, FOLDER_ID, FolderName("child"))
    folders = FolderRepo(
        [
            folder,
            child,
            Folder(UUID(int=12), PROJECT_ID, None, FolderName("readme.md")),
            Folder(
                UUID(int=11), PROJECT_ID, None, FolderName("readme (restored 1).md")
            ),
        ]
    )
    access = Access()
    await TrashFolder(
        folders,
        ProjectRepo(Project(PROJECT_ID, WORKSPACE_ID, ProjectName("Plan"))),
        access,
        Idempotency(),
    ).execute(ACTOR_ID, FOLDER_ID, idempotency_key="tf")
    assert folders.folders[child.folder_id] is child
    restored = await RestoreFolder(
        folders,
        ProjectRepo(Project(PROJECT_ID, WORKSPACE_ID, ProjectName("Plan"))),
        access,
        Idempotency(),
    ).execute(ACTOR_ID, FOLDER_ID, idempotency_key="rf")
    assert restored.name.display == "readme (restored 2).md"
