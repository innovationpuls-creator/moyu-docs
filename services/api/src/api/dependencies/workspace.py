from __future__ import annotations

from app_core.permission.application.workspace_ownership import TransferWorkspaceOwner
from app_core.workspace.application.folder_use_cases import (
    CreateFolder,
    MoveFolder,
    RenameFolder,
)
from app_core.workspace.application.project_use_cases import (
    CreateProject,
    GetProjectTree,
    RenameProject,
    RenameWorkspace,
)
from app_core.workspace.application.use_cases import CreateWorkspace, GetWorkspace
from app_infra.postgres.mutation_idempotency_repository import (
    PostgresMutationIdempotencyRepository,
)
from app_infra.postgres.permission_workspace_repository import (
    PostgresWorkspaceMembershipRepository,
)
from app_infra.postgres.workspace_composition import (
    build_create_folder_use_case,
    build_create_project_use_case,
    build_create_workspace_use_case,
    build_folder_lifecycle_use_cases,
    build_get_project_tree_use_case,
    build_get_workspace_use_case,
    build_move_folder_use_case,
    build_project_lifecycle_use_cases,
    build_rename_folder_use_case,
    build_rename_project_use_case,
    build_rename_workspace_use_case,
    build_transfer_workspace_owner_use_case,
)
from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from api.dependencies.auth import get_db_session


def get_create_workspace_use_case(
    session: AsyncSession = Depends(get_db_session),
) -> CreateWorkspace:
    return build_create_workspace_use_case(session)


def get_workspace_use_case(
    session: AsyncSession = Depends(get_db_session),
) -> GetWorkspace:
    return build_get_workspace_use_case(session)


def get_transfer_workspace_owner_use_case(
    session: AsyncSession = Depends(get_db_session),
) -> TransferWorkspaceOwner:
    return build_transfer_workspace_owner_use_case(session)


def get_rename_workspace_use_case(
    session: AsyncSession = Depends(get_db_session),
) -> RenameWorkspace:
    access, idempotency = _access_and_idempotency(session)
    return build_rename_workspace_use_case(session, access, idempotency)


def get_rename_project_use_case(
    session: AsyncSession = Depends(get_db_session),
) -> RenameProject:
    access, idempotency = _access_and_idempotency(session)
    return build_rename_project_use_case(session, access, idempotency)


def get_project_lifecycle_use_cases(session: AsyncSession = Depends(get_db_session)):
    access, idempotency = _access_and_idempotency(session)
    return build_project_lifecycle_use_cases(session, access, idempotency)


def get_rename_folder_use_case(
    session: AsyncSession = Depends(get_db_session),
) -> RenameFolder:
    access, idempotency = _access_and_idempotency(session)
    return build_rename_folder_use_case(session, access, idempotency)


def get_folder_lifecycle_use_cases(session: AsyncSession = Depends(get_db_session)):
    access, idempotency = _access_and_idempotency(session)
    return build_folder_lifecycle_use_cases(session, access, idempotency)


def _access_and_idempotency(session: AsyncSession):
    return (
        PostgresWorkspaceMembershipRepository(session),
        PostgresMutationIdempotencyRepository(session),
    )


def get_create_project_use_case(
    session: AsyncSession = Depends(get_db_session),
) -> CreateProject:
    access, idempotency = _access_and_idempotency(session)
    return build_create_project_use_case(session, access, idempotency)


def get_get_project_tree_use_case(
    session: AsyncSession = Depends(get_db_session),
) -> GetProjectTree:
    access = PostgresWorkspaceMembershipRepository(session)
    return build_get_project_tree_use_case(session, access)


def get_create_folder_use_case(
    session: AsyncSession = Depends(get_db_session),
) -> CreateFolder:
    access, idempotency = _access_and_idempotency(session)
    return build_create_folder_use_case(session, access, idempotency)


def get_move_folder_use_case(
    session: AsyncSession = Depends(get_db_session),
) -> MoveFolder:
    access, idempotency = _access_and_idempotency(session)
    return build_move_folder_use_case(session, access, idempotency)
