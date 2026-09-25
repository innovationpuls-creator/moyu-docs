from __future__ import annotations

from datetime import datetime, timedelta
from typing import Annotated, Any, cast
from uuid import UUID

from app_contracts.commands.permission.transfer_workspace_owner import (
    TransferWorkspaceOwner as TransferWorkspaceOwnerRequest,
)
from app_contracts.commands.permission.transfer_workspace_owner import (
    TransferWorkspaceOwnerResponse,
)
from app_contracts.commands.workspace.archive_project import (
    ArchiveProject as ArchiveProjectRequest,
)
from app_contracts.commands.workspace.archive_project import (
    ArchiveProjectResponse,
)
from app_contracts.commands.workspace.create_folder import (
    CreateFolder as CreateFolderRequest,
)
from app_contracts.commands.workspace.create_folder import (
    CreateFolderResponse,
)
from app_contracts.commands.workspace.create_project import (
    CreateProject as CreateProjectRequest,
)
from app_contracts.commands.workspace.create_project import (
    CreateProjectResponse,
)
from app_contracts.commands.workspace.create_workspace import (
    CreateWorkspace as CreateWorkspaceRequest,
)
from app_contracts.commands.workspace.create_workspace import (
    CreateWorkspaceResponse,
)
from app_contracts.commands.workspace.move_folder import (
    MoveFolder as MoveFolderRequest,
)
from app_contracts.commands.workspace.move_folder import (
    MoveFolderResponse,
)
from app_contracts.commands.workspace.rename_folder import (
    RenameFolder as RenameFolderRequest,
)
from app_contracts.commands.workspace.rename_folder import (
    RenameFolderResponse,
)
from app_contracts.commands.workspace.rename_project import (
    RenameProject as RenameProjectRequest,
)
from app_contracts.commands.workspace.rename_project import (
    RenameProjectResponse,
)
from app_contracts.commands.workspace.rename_workspace import (
    RenameWorkspace as RenameWorkspaceRequest,
)
from app_contracts.commands.workspace.rename_workspace import (
    RenameWorkspaceResponse,
)
from app_contracts.commands.workspace.restore_folder import (
    RestoreFolder as RestoreFolderRequest,
)
from app_contracts.commands.workspace.restore_folder import (
    RestoreFolderResponse,
)
from app_contracts.commands.workspace.restore_project import (
    RestoreProject as RestoreProjectRequest,
)
from app_contracts.commands.workspace.restore_project import (
    RestoreProjectResponse,
)
from app_contracts.commands.workspace.trash_folder import (
    TrashFolder as TrashFolderRequest,
)
from app_contracts.commands.workspace.trash_folder import (
    TrashFolderResponse,
)
from app_contracts.commands.workspace.trash_project import (
    TrashProject as TrashProjectRequest,
)
from app_contracts.commands.workspace.trash_project import (
    TrashProjectResponse,
)
from app_contracts.commands.workspace.unarchive_project import (
    UnarchiveProject as UnarchiveProjectRequest,
)
from app_contracts.commands.workspace.unarchive_project import (
    UnarchiveProjectResponse,
)
from app_contracts.queries.workspace.get_project_tree import (
    FolderLifecycle as ContractFolderLifecycle,
)
from app_contracts.queries.workspace.get_project_tree import (
    FolderSummary,
    GetProjectTreeResponse,
    ProjectSummary,
)
from app_contracts.queries.workspace.get_project_tree import (
    ProjectLifecycle as ContractProjectLifecycle,
)
from app_contracts.queries.workspace.get_workspace import (
    GetWorkspaceResponse,
    Lifecycle,
)
from app_core.common.exceptions import ConflictError
from app_core.permission.application.workspace_ownership import TransferWorkspaceOwner
from app_core.session.domain.session import Session
from app_core.workspace.application.folder_use_cases import (
    CreateFolder,
    MoveFolder,
    RenameFolder,
)
from app_core.workspace.application.project_use_cases import (
    CreateProject,
    GetProjectTree,
    RenameProject,
)
from app_core.workspace.application.use_cases import (
    CreateWorkspace as CreateWorkspaceUseCase,
)
from app_core.workspace.application.use_cases import (
    GetWorkspace as GetWorkspaceUseCase,
)
from app_infra.postgres.audit.audit_repository import PostgresAuditRepository
from app_infra.postgres.resource.resource_repository import PostgresResourceRepository
from app_infra.postgres.workspace_composition import (
    FolderLifecycleUses,
    ProjectLifecycleUses,
)
from fastapi import APIRouter, Depends, Header, status
from sqlalchemy.ext.asyncio import AsyncSession

from api.dependencies.auth import get_current_session, get_db_session
from api.dependencies.workspace import (
    get_create_folder_use_case,
    get_create_project_use_case,
    get_create_workspace_use_case,
    get_folder_lifecycle_use_cases,
    get_get_project_tree_use_case,
    get_move_folder_use_case,
    get_project_lifecycle_use_cases,
    get_rename_folder_use_case,
    get_rename_project_use_case,
    get_rename_workspace_use_case,
    get_transfer_workspace_owner_use_case,
    get_workspace_use_case,
)

router = APIRouter()


@router.post(
    "/workspaces",
    response_model=CreateWorkspaceResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_workspace(
    request: CreateWorkspaceRequest,
    current: Annotated[Session, Depends(get_current_session)],
    use_case: Annotated[CreateWorkspaceUseCase, Depends(get_create_workspace_use_case)],
) -> CreateWorkspaceResponse:
    result = await use_case.execute(
        current.account_id,
        request.name,
        idempotency_key=str(request.idempotencyKey),
    )
    return CreateWorkspaceResponse(
        workspaceId=result.workspace.workspace_id,
        name=result.workspace.name.display,
        ownerAccountId=result.owner_account_id,
        createdAt=result.workspace.created_at,
    )


@router.get("/workspaces/{workspace_id}", response_model=GetWorkspaceResponse)
async def get_workspace(
    workspace_id: UUID,
    current: Annotated[Session, Depends(get_current_session)],
    use_case: Annotated[GetWorkspaceUseCase, Depends(get_workspace_use_case)],
) -> GetWorkspaceResponse:
    result = await use_case.execute(current.account_id, workspace_id)
    return GetWorkspaceResponse(
        workspaceId=result.workspace.workspace_id,
        name=result.workspace.name.display,
        ownerAccountId=result.owner_account_id,
        lifecycle=Lifecycle(result.workspace.lifecycle.value),
        createdAt=result.workspace.created_at,
        updatedAt=result.workspace.updated_at,
    )


@router.post(
    "/workspaces/{workspace_id}/owner",
    response_model=TransferWorkspaceOwnerResponse,
)
async def transfer_workspace_owner(
    workspace_id: UUID,
    request: TransferWorkspaceOwnerRequest,
    current: Annotated[Session, Depends(get_current_session)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
    use_case: Annotated[
        TransferWorkspaceOwner, Depends(get_transfer_workspace_owner_use_case)
    ],
    header_idempotency_key: Annotated[
        UUID | None, Header(alias="Idempotency-Key")
    ] = None,
) -> TransferWorkspaceOwnerResponse:
    if request.workspaceId != workspace_id:
        raise ConflictError(
            "Path and body Workspace IDs differ.", "WORKSPACE_OWNER_TRANSFER_INVALID"
        )
    if (
        header_idempotency_key is not None
        and header_idempotency_key != request.idempotencyKey
    ):
        raise ConflictError(
            "Header and body idempotency keys differ.",
            "IDEMPOTENCY_KEY_CONFLICT",
        )
    result = await use_case.execute(
        current.account_id,
        workspace_id,
        request.newOwnerAccountId,
        str(request.idempotencyKey),
    )
    # Audit: Owner transfer is a high-risk permission change (arch 23).
    await PostgresAuditRepository(session).record(
        actor_account_id=current.account_id,
        action="workspace.owner.transferred",
        target_type="workspace",
        target_id=workspace_id,
        detail={"newOwnerAccountId": str(request.newOwnerAccountId)},
    )
    return TransferWorkspaceOwnerResponse(
        workspaceId=result.workspace_id,
        previousOwnerAccountId=result.previous_owner_account_id,
        newOwnerAccountId=result.new_owner_account_id,
        previousOwnerRemainsMember=True,
        independentProjectOwnerRowsChanged=False,
        transferredAt=result.transferred_at,
    )


@router.post(
    "/workspaces/{workspace_id}/projects",
    response_model=CreateProjectResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_project(
    workspace_id: UUID,
    request: CreateProjectRequest,
    current: Annotated[Session, Depends(get_current_session)],
    use_case: Annotated[CreateProject, Depends(get_create_project_use_case)],
) -> CreateProjectResponse:
    if request.workspaceId != workspace_id:
        raise ConflictError(
            "Path and body Workspace IDs differ.", "WORKSPACE_REQUEST_MISMATCH"
        )
    result = await use_case.execute(
        current.account_id,
        workspace_id,
        request.name,
        idempotency_key=str(request.idempotencyKey),
    )
    return CreateProjectResponse(
        projectId=result.project_id,
        workspaceId=result.workspace_id,
        name=result.name.display,
        createdAt=cast(datetime, result.created_at),
    )


@router.post(
    "/projects/{project_id}/folders",
    response_model=CreateFolderResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_folder(
    project_id: UUID,
    request: CreateFolderRequest,
    current: Annotated[Session, Depends(get_current_session)],
    use_case: Annotated[CreateFolder, Depends(get_create_folder_use_case)],
) -> CreateFolderResponse:
    if request.projectId != project_id:
        raise ConflictError(
            "Path and body Project IDs differ.", "WORKSPACE_REQUEST_MISMATCH"
        )
    result = await use_case.execute(
        current.account_id,
        project_id,
        request.parentFolderId,
        request.name,
        idempotency_key=str(request.idempotencyKey),
    )
    return CreateFolderResponse(
        folderId=result.folder_id,
        projectId=result.project_id,
        parentFolderId=result.parent_folder_id,
        name=result.name.display,
        createdAt=cast(datetime, result.created_at),
    )


@router.post(
    "/folders/{folder_id}/move",
    response_model=MoveFolderResponse,
)
async def move_folder(
    folder_id: UUID,
    request: MoveFolderRequest,
    current: Annotated[Session, Depends(get_current_session)],
    use_case: Annotated[MoveFolder, Depends(get_move_folder_use_case)],
) -> MoveFolderResponse:
    if request.folderId != folder_id:
        raise ConflictError(
            "Path and body Folder IDs differ.", "WORKSPACE_REQUEST_MISMATCH"
        )
    result = await use_case.execute(
        current.account_id,
        folder_id,
        request.destinationParentFolderId,
        idempotency_key=str(request.idempotencyKey),
    )
    return MoveFolderResponse(
        folderId=result.folder_id,
        projectId=result.project_id,
        parentFolderId=result.parent_folder_id,
        updatedAt=cast(datetime, result.updated_at),
    )


@router.patch("/workspaces/{workspace_id}", response_model=RenameWorkspaceResponse)
async def rename_workspace(
    workspace_id: UUID,
    request: RenameWorkspaceRequest,
    current: Annotated[Session, Depends(get_current_session)],
    use_case: Annotated[Any, Depends(get_rename_workspace_use_case)],
) -> RenameWorkspaceResponse:
    if request.workspaceId != workspace_id:
        raise ConflictError(
            "Path and body Workspace IDs differ.", "WORKSPACE_REQUEST_MISMATCH"
        )
    result = await use_case.execute(
        current.account_id,
        workspace_id,
        request.name,
        idempotency_key=str(request.idempotencyKey),
    )
    return RenameWorkspaceResponse(
        workspaceId=result.workspace_id,
        name=result.name.display,
        updatedAt=cast(datetime, result.updated_at),
    )


@router.patch("/projects/{project_id}", response_model=RenameProjectResponse)
async def rename_project(
    project_id: UUID,
    request: RenameProjectRequest,
    current: Annotated[Session, Depends(get_current_session)],
    use_case: Annotated[RenameProject, Depends(get_rename_project_use_case)],
) -> RenameProjectResponse:
    if request.projectId != project_id:
        raise ConflictError(
            "Path and body Project IDs differ.", "WORKSPACE_REQUEST_MISMATCH"
        )
    result = await use_case.execute(
        current.account_id,
        project_id,
        request.name,
        idempotency_key=str(request.idempotencyKey),
    )
    return RenameProjectResponse(
        projectId=result.project_id,
        name=result.name.display,
        updatedAt=cast(datetime, result.updated_at),
    )


@router.patch("/folders/{folder_id}", response_model=RenameFolderResponse)
async def rename_folder(
    folder_id: UUID,
    request: RenameFolderRequest,
    current: Annotated[Session, Depends(get_current_session)],
    use_case: Annotated[RenameFolder, Depends(get_rename_folder_use_case)],
) -> RenameFolderResponse:
    if request.folderId != folder_id:
        raise ConflictError(
            "Path and body Folder IDs differ.", "WORKSPACE_REQUEST_MISMATCH"
        )
    result = await use_case.execute(
        current.account_id,
        folder_id,
        request.name,
        idempotency_key=str(request.idempotencyKey),
    )
    return RenameFolderResponse(
        folderId=result.folder_id,
        projectId=result.project_id,
        parentFolderId=result.parent_folder_id,
        name=result.name.display,
        updatedAt=cast(datetime, result.updated_at),
    )


@router.post("/projects/{project_id}/archive", response_model=ArchiveProjectResponse)
async def archive_project(
    project_id: UUID,
    request: ArchiveProjectRequest,
    current: Annotated[Session, Depends(get_current_session)],
    use_cases: Annotated[
        ProjectLifecycleUses, Depends(get_project_lifecycle_use_cases)
    ],
) -> ArchiveProjectResponse:
    result = await use_cases.archive.execute(
        current.account_id, project_id, idempotency_key=str(request.idempotencyKey)
    )
    return ArchiveProjectResponse(
        projectId=result.project_id,
        lifecycle="Archived",
        updatedAt=cast(datetime, result.updated_at),
    )


@router.post(
    "/projects/{project_id}/unarchive", response_model=UnarchiveProjectResponse
)
async def unarchive_project(
    project_id: UUID,
    request: UnarchiveProjectRequest,
    current: Annotated[Session, Depends(get_current_session)],
    use_cases: Annotated[
        ProjectLifecycleUses, Depends(get_project_lifecycle_use_cases)
    ],
) -> UnarchiveProjectResponse:
    result = await use_cases.unarchive.execute(
        current.account_id, project_id, idempotency_key=str(request.idempotencyKey)
    )
    return UnarchiveProjectResponse(
        projectId=result.project_id,
        lifecycle="Active",
        updatedAt=cast(datetime, result.updated_at),
    )


@router.post("/projects/{project_id}/trash", response_model=TrashProjectResponse)
async def trash_project(
    project_id: UUID,
    request: TrashProjectRequest,
    current: Annotated[Session, Depends(get_current_session)],
    use_cases: Annotated[
        ProjectLifecycleUses, Depends(get_project_lifecycle_use_cases)
    ],
) -> TrashProjectResponse:
    result = await use_cases.trash.execute(
        current.account_id, project_id, idempotency_key=str(request.idempotencyKey)
    )
    timestamp = cast(datetime, result.updated_at)
    return TrashProjectResponse(
        projectId=result.project_id,
        lifecycle="Trashed",
        effectiveDescendantLifecycle="Trashed",
        trashedAt=timestamp,
        # Canonical 30-day Purge-eligibility window from the authoritative trash
        # timestamp; Purge execution itself is a deferred Feature.
        purgeEligibleAt=timestamp + timedelta(days=30),
    )


@router.post("/projects/{project_id}/restore", response_model=RestoreProjectResponse)
async def restore_project(
    project_id: UUID,
    request: RestoreProjectRequest,
    current: Annotated[Session, Depends(get_current_session)],
    use_cases: Annotated[
        ProjectLifecycleUses, Depends(get_project_lifecycle_use_cases)
    ],
) -> RestoreProjectResponse:
    result = await use_cases.restore.execute(
        current.account_id, project_id, idempotency_key=str(request.idempotencyKey)
    )
    return RestoreProjectResponse(
        projectId=result.project_id,
        lifecycle="Active",
        restoredDescendantCount=0,
        restoredAt=cast(datetime, result.updated_at),
    )


@router.post("/folders/{folder_id}/trash", response_model=TrashFolderResponse)
async def trash_folder(
    folder_id: UUID,
    request: TrashFolderRequest,
    current: Annotated[Session, Depends(get_current_session)],
    use_cases: Annotated[FolderLifecycleUses, Depends(get_folder_lifecycle_use_cases)],
) -> TrashFolderResponse:
    result = await use_cases.trash.execute(
        current.account_id, folder_id, idempotency_key=str(request.idempotencyKey)
    )
    timestamp = cast(datetime, result.updated_at)
    return TrashFolderResponse(
        folderId=result.folder_id,
        lifecycle="Trashed",
        effectiveDescendantLifecycle="Trashed",
        trashedAt=timestamp,
        # Canonical 30-day Purge-eligibility window from the authoritative trash
        # timestamp; Purge execution itself is a deferred Feature.
        purgeEligibleAt=timestamp + timedelta(days=30),
    )


@router.post("/folders/{folder_id}/restore", response_model=RestoreFolderResponse)
async def restore_folder(
    folder_id: UUID,
    request: RestoreFolderRequest,
    current: Annotated[Session, Depends(get_current_session)],
    use_cases: Annotated[FolderLifecycleUses, Depends(get_folder_lifecycle_use_cases)],
) -> RestoreFolderResponse:
    result = await use_cases.restore.execute(
        current.account_id, folder_id, idempotency_key=str(request.idempotencyKey)
    )
    return RestoreFolderResponse(
        folderId=result.folder_id,
        projectId=result.project_id,
        parentFolderId=result.parent_folder_id,
        name=result.name.display,
        lifecycle="Active",
        restoredDescendantCount=0,
        restoredAt=cast(datetime, result.updated_at),
    )


@router.get("/projects/{project_id}", response_model=GetProjectTreeResponse)
async def get_project_tree(
    project_id: UUID,
    current: Annotated[Session, Depends(get_current_session)],
    use_case: Annotated[GetProjectTree, Depends(get_get_project_tree_use_case)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> GetProjectTreeResponse:
    result = await use_case.execute(current.account_id, project_id)
    resources = await PostgresResourceRepository(session).list_by_project(project_id)
    return GetProjectTreeResponse(
        workspaceId=result.workspace_id,
        projectId=result.project.project_id,
        project=ProjectSummary(
            name=result.project.name.display,
            lifecycle=ContractProjectLifecycle(result.project.lifecycle.value),
        ),
        folders=[
            FolderSummary(
                folderId=folder.folder_id,
                parentFolderId=folder.parent_folder_id,
                name=folder.name.display,
                lifecycle=ContractFolderLifecycle(folder.lifecycle.value),
                hasChildren=any(
                    child.parent_folder_id == folder.folder_id
                    for child in result.folders
                )
                or any(
                    resource.folder_id == folder.folder_id
                    and resource.lifecycle == "Active"
                    for resource in resources
                ),
            )
            for folder in result.folders
        ],
        nextCursor=result.next_cursor,
    )
