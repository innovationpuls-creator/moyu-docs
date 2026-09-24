from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from app_core.account.domain.account import AccountStatus
from app_core.permission.application.workspace_ownership import (
    GetCurrentWorkspaceOwner,
    GrantInitialWorkspaceOwner,
    TransferWorkspaceOwner,
)
from app_core.permission.ports.workspace_access import WorkspaceAccessPort
from app_core.workspace.application.folder_use_cases import (
    CreateFolder,
    MoveFolder,
    RenameFolder,
    RestoreFolder,
    TrashFolder,
)
from app_core.workspace.application.project_use_cases import (
    ArchiveProject,
    CreateProject,
    GetProjectTree,
    RenameProject,
    RenameWorkspace,
    RestoreProject,
    TrashProject,
    UnarchiveProject,
)
from app_core.workspace.application.use_cases import CreateWorkspace, GetWorkspace
from app_core.workspace.ports.mutation_idempotency import MutationIdempotencyPort
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app_infra.postgres.folder_repository import PostgresFolderRepository
from app_infra.postgres.permission_workspace_repository import (
    PostgresWorkspaceMembershipRepository,
)
from app_infra.postgres.project_repository import PostgresProjectRepository
from app_infra.postgres.workspace_event_publisher import (
    PostgresLifecycleEventPublisher,
)
from app_infra.postgres.workspace_idempotency_repository import (
    PostgresWorkspaceIdempotencyRepository,
)
from app_infra.postgres.workspace_repository import PostgresWorkspaceRepository


class PostgresAccountWorkspaceEligibility:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def workspace_creation_status(self, actor_id: UUID) -> AccountStatus | None:
        raw_status = await self._session.scalar(
            text("SELECT status FROM auth.accounts WHERE account_id=:account_id"),
            {"account_id": actor_id},
        )
        if raw_status is None:
            return None
        try:
            return AccountStatus(raw_status)
        except ValueError as exc:
            raise RuntimeError("Account status is not recognized") from exc


def build_transfer_workspace_owner_use_case(
    session: AsyncSession,
) -> TransferWorkspaceOwner:
    return TransferWorkspaceOwner(PostgresWorkspaceMembershipRepository(session))


def build_get_workspace_use_case(session: AsyncSession) -> GetWorkspace:
    memberships = PostgresWorkspaceMembershipRepository(session)
    return GetWorkspace(
        PostgresWorkspaceRepository(session),
        memberships,
        GetCurrentWorkspaceOwner(memberships),
    )


def build_create_workspace_use_case(
    session: AsyncSession,
    *,
    now: Callable[[], datetime] | None = None,
) -> CreateWorkspace:
    memberships = PostgresWorkspaceMembershipRepository(session)
    return CreateWorkspace(
        PostgresWorkspaceRepository(session),
        GrantInitialWorkspaceOwner(memberships),
        PostgresAccountWorkspaceEligibility(session),
        PostgresWorkspaceIdempotencyRepository(session),
        PostgresLifecycleEventPublisher(session),
        now=now or (lambda: datetime.now(UTC)),
    )


def build_create_project_use_case(
    session: AsyncSession,
    access: WorkspaceAccessPort,
    idempotency: MutationIdempotencyPort,
    *,
    now: Callable[[], datetime] | None = None,
) -> CreateProject:
    return CreateProject(
        PostgresProjectRepository(session),
        access,
        idempotency=idempotency,
        events=PostgresLifecycleEventPublisher(session),
        now=now or (lambda: datetime.now(UTC)),
    )


def build_rename_project_use_case(
    session: AsyncSession,
    access: WorkspaceAccessPort,
    idempotency: MutationIdempotencyPort,
) -> RenameProject:
    return RenameProject(
        PostgresProjectRepository(session),
        access,
        idempotency=idempotency,
    )


@dataclass(frozen=True)
class ProjectLifecycleUses:
    archive: ArchiveProject
    unarchive: UnarchiveProject
    trash: TrashProject
    restore: RestoreProject


@dataclass(frozen=True)
class FolderLifecycleUses:
    trash: TrashFolder
    restore: RestoreFolder


def build_project_lifecycle_use_cases(
    session: AsyncSession,
    access: WorkspaceAccessPort,
    idempotency: MutationIdempotencyPort,
) -> ProjectLifecycleUses:
    projects = PostgresProjectRepository(session)

    def publisher() -> PostgresLifecycleEventPublisher:
        return PostgresLifecycleEventPublisher(session)

    return ProjectLifecycleUses(
        ArchiveProject(projects, access, idempotency, events=publisher()),
        UnarchiveProject(projects, access, idempotency, events=publisher()),
        TrashProject(projects, access, idempotency, events=publisher()),
        RestoreProject(projects, access, idempotency, events=publisher()),
    )


def build_get_project_tree_use_case(
    session: AsyncSession, access: WorkspaceAccessPort
) -> GetProjectTree:
    return GetProjectTree(
        PostgresWorkspaceRepository(session),
        PostgresProjectRepository(session),
        PostgresFolderRepository(session),
        access,
    )


def build_create_folder_use_case(
    session: AsyncSession,
    access: WorkspaceAccessPort,
    idempotency: MutationIdempotencyPort,
    *,
    now: Callable[[], datetime] | None = None,
) -> CreateFolder:
    return CreateFolder(
        PostgresProjectRepository(session),
        PostgresFolderRepository(session),
        access,
        idempotency=idempotency,
        events=PostgresLifecycleEventPublisher(session),
        now=now or (lambda: datetime.now(UTC)),
    )


def build_rename_folder_use_case(
    session: AsyncSession,
    access: WorkspaceAccessPort,
    idempotency: MutationIdempotencyPort,
) -> RenameFolder:
    return RenameFolder(
        PostgresProjectRepository(session),
        PostgresFolderRepository(session),
        access,
        idempotency,
        events=PostgresLifecycleEventPublisher(session),
    )


def build_move_folder_use_case(
    session: AsyncSession,
    access: WorkspaceAccessPort,
    idempotency: MutationIdempotencyPort,
    *,
    now: Callable[[], datetime] | None = None,
) -> MoveFolder:
    return MoveFolder(
        PostgresFolderRepository(session),
        PostgresProjectRepository(session),
        access,
        idempotency,
        events=PostgresLifecycleEventPublisher(session),
        now=now or (lambda: datetime.now(UTC)),
    )


def build_folder_lifecycle_use_cases(
    session: AsyncSession,
    access: WorkspaceAccessPort,
    idempotency: MutationIdempotencyPort,
    *,
    now: Callable[[], datetime] | None = None,
) -> FolderLifecycleUses:
    folders = PostgresFolderRepository(session)
    projects = PostgresProjectRepository(session)
    clock = now or (lambda: datetime.now(UTC))
    publisher = PostgresLifecycleEventPublisher(session)
    return FolderLifecycleUses(
        TrashFolder(
            folders, projects, access, idempotency, events=publisher, now=clock
        ),
        RestoreFolder(
            folders, projects, access, idempotency, events=publisher, now=clock
        ),
    )


def build_rename_workspace_use_case(
    session: AsyncSession,
    access: WorkspaceAccessPort,
    idempotency: MutationIdempotencyPort,
    *,
    now: Callable[[], datetime] | None = None,
) -> RenameWorkspace:
    return RenameWorkspace(
        PostgresWorkspaceRepository(session),
        access,
        idempotency=idempotency,
        now=now or (lambda: datetime.now(UTC)),
    )
