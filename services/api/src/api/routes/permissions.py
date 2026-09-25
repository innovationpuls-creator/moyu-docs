from __future__ import annotations

from typing import Annotated
from uuid import UUID

from app_contracts.commands.permission.accept_workspace_invitation import (
    AcceptWorkspaceInvitation as AcceptWorkspaceInvitationRequest,
)
from app_contracts.commands.permission.accept_workspace_invitation import (
    AcceptWorkspaceInvitationResponse,
)
from app_contracts.commands.permission.accept_workspace_invitation import (
    MembershipKind as AcceptedMembershipKind,
)
from app_contracts.commands.permission.create_workspace_invitation import (
    CreateWorkspaceInvitation as CreateWorkspaceInvitationRequest,
)
from app_contracts.commands.permission.create_workspace_invitation import (
    CreateWorkspaceInvitationResponse,
)
from app_contracts.commands.permission.remove_project_member import (
    RemoveProjectMember as RemoveProjectMemberRequest,
)
from app_contracts.commands.permission.remove_project_member import (
    RemoveProjectMemberResponse,
)
from app_contracts.commands.permission.remove_resource_permission import (
    RemoveResourcePermission as RemoveResourcePermissionRequest,
)
from app_contracts.commands.permission.remove_resource_permission import (
    RemoveResourcePermissionResponse,
)
from app_contracts.commands.permission.remove_workspace_member import (
    RemoveWorkspaceMember as RemoveWorkspaceMemberRequest,
)
from app_contracts.commands.permission.remove_workspace_member import (
    RemoveWorkspaceMemberResponse,
)
from app_contracts.commands.permission.revoke_workspace_invitation import (
    RevokeWorkspaceInvitation as RevokeWorkspaceInvitationRequest,
)
from app_contracts.commands.permission.revoke_workspace_invitation import (
    RevokeWorkspaceInvitationResponse,
)
from app_contracts.commands.permission.revoke_workspace_invitation import (
    State as InvitationRevocationState,
)
from app_contracts.commands.permission.set_project_member_role import (
    MembershipKind as ProjectMembershipKind,
)
from app_contracts.commands.permission.set_project_member_role import (
    Role as ProjectRoleContract,
)
from app_contracts.commands.permission.set_project_member_role import (
    SetProjectMemberRole as SetProjectMemberRoleRequest,
)
from app_contracts.commands.permission.set_project_member_role import (
    SetProjectMemberRoleResponse,
)
from app_contracts.commands.permission.set_resource_permission import (
    Role as ResourceRoleContract,
)
from app_contracts.commands.permission.set_resource_permission import (
    SetResourcePermission as SetResourcePermissionRequest,
)
from app_contracts.commands.permission.set_resource_permission import (
    SetResourcePermissionResponse,
)
from app_contracts.queries.permission.get_resource_capabilities import (
    GetResourceCapabilitiesResponse,
)
from app_contracts.queries.permission.list_project_members import (
    ListProjectMembersResponse,
)
from app_contracts.queries.permission.list_project_members import (
    Member as ProjectMemberContract,
)
from app_contracts.queries.permission.list_project_members import (
    MembershipKind as ProjectMemberKind,
)
from app_contracts.queries.permission.list_project_members import (
    Role as ListedProjectRole,
)
from app_contracts.queries.permission.list_resource_permissions import (
    ListResourcePermissionsResponse,
)
from app_contracts.queries.permission.list_resource_permissions import (
    Permission as ResourcePermissionContract,
)
from app_contracts.queries.permission.list_resource_permissions import (
    Role as ListedResourceRole,
)
from app_contracts.queries.permission.list_workspace_invitations import (
    Invitation as WorkspaceInvitationContract,
)
from app_contracts.queries.permission.list_workspace_invitations import (
    ListWorkspaceInvitationsResponse,
)
from app_contracts.queries.permission.list_workspace_invitations import (
    State as WorkspaceInvitationState,
)
from app_contracts.queries.permission.list_workspace_members import (
    ListWorkspaceMembersResponse,
)
from app_contracts.queries.permission.list_workspace_members import (
    Member as WorkspaceMemberContract,
)
from app_contracts.queries.permission.list_workspace_members import (
    MembershipKind as WorkspaceMembershipKind,
)
from app_core.common.exceptions import ConflictError
from app_core.permission.application.administration import PermissionAdministration
from app_core.permission.domain.access_control import (
    PermissionCapability,
    PermissionRole,
)
from app_core.permission.domain.collaboration import InvitationAcceptanceExpired
from app_core.session.domain.session import Session
from fastapi import APIRouter, Depends, Header, status
from fastapi.responses import JSONResponse

from api.dependencies.auth import get_current_session
from api.dependencies.permission import get_permission_administration
from api.middleware.error_handler import _build_envelope

router = APIRouter()


@router.get(
    "/resources/{resource_id}/capabilities",
    response_model=GetResourceCapabilitiesResponse,
)
async def get_resource_capabilities(
    resource_id: UUID,
    current: Annotated[Session, Depends(get_current_session)],
    use_case: Annotated[
        PermissionAdministration, Depends(get_permission_administration)
    ],
) -> GetResourceCapabilitiesResponse:
    permission = await use_case.get_resource_capabilities(
        current.account_id, resource_id
    )
    return GetResourceCapabilitiesResponse(
        resourceId=resource_id,
        canRead=permission.allows(PermissionCapability.READ),
        canUpdate=permission.allows(PermissionCapability.EDIT),
        canComment=permission.allows(PermissionCapability.COMMENT),
        canManage=permission.allows(PermissionCapability.MANAGE),
        canResolveCommentThread=permission.allows(PermissionCapability.RESOLVE_COMMENT),
        canReopenCommentThread=permission.allows(PermissionCapability.REOPEN_COMMENT),
    )


@router.post(
    "/workspaces/{workspace_id}/invitations",
    response_model=CreateWorkspaceInvitationResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_workspace_invitation(
    workspace_id: UUID,
    request: CreateWorkspaceInvitationRequest,
    current: Annotated[Session, Depends(get_current_session)],
    use_case: Annotated[
        PermissionAdministration, Depends(get_permission_administration)
    ],
    idempotency_key: Annotated[UUID, Header(alias="Idempotency-Key")],
) -> CreateWorkspaceInvitationResponse:
    if request.workspaceId != workspace_id:
        raise ConflictError(
            "Path and body Workspace IDs differ.", "WORKSPACE_REQUEST_MISMATCH"
        )
    created = await use_case.create_workspace_invitation(
        current.account_id,
        workspace_id,
        str(request.targetEmail),
        str(idempotency_key),
        request.expiresInDays or 7,
    )
    invitation = created.invitation
    return CreateWorkspaceInvitationResponse(
        invitationId=invitation.invitation_id,
        workspaceId=invitation.workspace_id,
        targetEmail=invitation.target_email,
        role="Member",
        state="Pending",
        expiresAt=invitation.expires_at,
        createdBy=invitation.created_by,
        createdAt=invitation.created_at,
        invitationUrl=created.invitation_url,
    )


@router.get(
    "/workspaces/{workspace_id}/members",
    response_model=ListWorkspaceMembersResponse,
)
async def list_workspace_members(
    workspace_id: UUID,
    current: Annotated[Session, Depends(get_current_session)],
    use_case: Annotated[
        PermissionAdministration, Depends(get_permission_administration)
    ],
) -> ListWorkspaceMembersResponse:
    members = await use_case.list_workspace_members(current.account_id, workspace_id)
    return ListWorkspaceMembersResponse(
        members=[
            WorkspaceMemberContract(
                accountId=member.account_id,
                email=member.email,
                membershipKind=WorkspaceMembershipKind(member.membership_kind),
                createdAt=member.created_at,
            )
            for member in members
        ]
    )


@router.get(
    "/workspaces/{workspace_id}/invitations",
    response_model=ListWorkspaceInvitationsResponse,
)
async def list_workspace_invitations(
    workspace_id: UUID,
    current: Annotated[Session, Depends(get_current_session)],
    use_case: Annotated[
        PermissionAdministration, Depends(get_permission_administration)
    ],
) -> ListWorkspaceInvitationsResponse:
    invitations = await use_case.list_workspace_invitations(
        current.account_id, workspace_id
    )
    return ListWorkspaceInvitationsResponse(
        invitations=[
            WorkspaceInvitationContract(
                invitationId=item.invitation_id,
                workspaceId=item.workspace_id,
                targetEmail=item.target_email,
                targetAccountId=item.target_account_id,
                role="Member",
                state=WorkspaceInvitationState(item.state),
                expiresAt=item.expires_at,
                createdBy=item.created_by,
                createdAt=item.created_at,
                acceptedAt=item.accepted_at,
            )
            for item in invitations
        ]
    )


@router.post(
    "/invitations/accept",
    response_model=AcceptWorkspaceInvitationResponse,
)
async def accept_workspace_invitation(
    request: AcceptWorkspaceInvitationRequest,
    current: Annotated[Session, Depends(get_current_session)],
    use_case: Annotated[
        PermissionAdministration, Depends(get_permission_administration)
    ],
) -> AcceptWorkspaceInvitationResponse | JSONResponse:
    member = await use_case.accept_workspace_invitation(
        current.account_id, request.token
    )
    if isinstance(member, InvitationAcceptanceExpired):
        envelope = _build_envelope(
            category="Conflict",
            error_code="INVITATION_EXPIRED",
            message="Invitation has expired.",
        )
        return JSONResponse(
            status_code=status.HTTP_409_CONFLICT,
            content=envelope.model_dump(mode="json"),
        )
    return AcceptWorkspaceInvitationResponse(
        workspaceId=member.workspace_id,
        accountId=member.account_id,
        membershipKind=AcceptedMembershipKind(member.membership_kind),
        email=member.email,
        createdAt=member.created_at,
    )


@router.delete(
    "/workspaces/{workspace_id}/invitations/{invitation_id}",
    response_model=RevokeWorkspaceInvitationResponse,
)
async def revoke_workspace_invitation(
    workspace_id: UUID,
    invitation_id: UUID,
    request: RevokeWorkspaceInvitationRequest,
    current: Annotated[Session, Depends(get_current_session)],
    use_case: Annotated[
        PermissionAdministration, Depends(get_permission_administration)
    ],
    idempotency_key: Annotated[UUID, Header(alias="Idempotency-Key")],
) -> RevokeWorkspaceInvitationResponse:
    if (request.workspaceId, request.invitationId) != (workspace_id, invitation_id):
        raise ConflictError(
            "Path and body Invitation IDs differ.", "WORKSPACE_REQUEST_MISMATCH"
        )
    invitation = await use_case.revoke_workspace_invitation(
        current.account_id, workspace_id, invitation_id, str(idempotency_key)
    )
    return RevokeWorkspaceInvitationResponse(
        invitationId=invitation.invitation_id,
        state=InvitationRevocationState(invitation.state),
        expiresAt=invitation.expires_at,
    )


@router.delete(
    "/workspaces/{workspace_id}/members/{account_id}",
    response_model=RemoveWorkspaceMemberResponse,
)
async def remove_workspace_member(
    workspace_id: UUID,
    account_id: UUID,
    request: RemoveWorkspaceMemberRequest,
    current: Annotated[Session, Depends(get_current_session)],
    use_case: Annotated[
        PermissionAdministration, Depends(get_permission_administration)
    ],
    idempotency_key: Annotated[UUID, Header(alias="Idempotency-Key")],
) -> RemoveWorkspaceMemberResponse:
    if (request.workspaceId, request.accountId) != (workspace_id, account_id):
        raise ConflictError(
            "Path and body membership IDs differ.", "WORKSPACE_REQUEST_MISMATCH"
        )
    await use_case.remove_workspace_member(
        current.account_id, workspace_id, account_id, str(idempotency_key)
    )
    return RemoveWorkspaceMemberResponse(
        removed=True, workspaceId=workspace_id, accountId=account_id
    )


@router.get("/projects/{project_id}/members", response_model=ListProjectMembersResponse)
async def list_project_members(
    project_id: UUID,
    current: Annotated[Session, Depends(get_current_session)],
    use_case: Annotated[
        PermissionAdministration, Depends(get_permission_administration)
    ],
) -> ListProjectMembersResponse:
    members = await use_case.list_project_members(current.account_id, project_id)
    return ListProjectMembersResponse(
        members=[
            ProjectMemberContract(
                projectId=member.project_id,
                accountId=member.account_id,
                email=member.email,
                role=ListedProjectRole(member.role.value),
                membershipKind=ProjectMemberKind(member.membership_kind),
                createdAt=member.created_at,
                updatedAt=member.updated_at,
            )
            for member in members
        ]
    )


@router.put(
    "/projects/{project_id}/members/{account_id}",
    response_model=SetProjectMemberRoleResponse,
)
async def set_project_member_role(
    project_id: UUID,
    account_id: UUID,
    request: SetProjectMemberRoleRequest,
    current: Annotated[Session, Depends(get_current_session)],
    use_case: Annotated[
        PermissionAdministration, Depends(get_permission_administration)
    ],
    idempotency_key: Annotated[UUID, Header(alias="Idempotency-Key")],
) -> SetProjectMemberRoleResponse:
    if (request.projectId, request.accountId) != (project_id, account_id):
        raise ConflictError(
            "Path and body Project IDs differ.", "WORKSPACE_REQUEST_MISMATCH"
        )
    member = await use_case.set_project_member_role(
        current.account_id,
        project_id,
        account_id,
        PermissionRole(request.role.value),
        str(idempotency_key),
    )
    return SetProjectMemberRoleResponse(
        projectId=member.project_id,
        accountId=member.account_id,
        email=member.email,
        role=ProjectRoleContract(member.role.value),
        membershipKind=ProjectMembershipKind(member.membership_kind),
        createdAt=member.created_at,
        updatedAt=member.updated_at,
    )


@router.delete(
    "/projects/{project_id}/members/{account_id}",
    response_model=RemoveProjectMemberResponse,
)
async def remove_project_member(
    project_id: UUID,
    account_id: UUID,
    request: RemoveProjectMemberRequest,
    current: Annotated[Session, Depends(get_current_session)],
    use_case: Annotated[
        PermissionAdministration, Depends(get_permission_administration)
    ],
    idempotency_key: Annotated[UUID, Header(alias="Idempotency-Key")],
) -> RemoveProjectMemberResponse:
    if (request.projectId, request.accountId) != (project_id, account_id):
        raise ConflictError(
            "Path and body Project IDs differ.", "WORKSPACE_REQUEST_MISMATCH"
        )
    await use_case.remove_project_member(
        current.account_id, project_id, account_id, str(idempotency_key)
    )
    return RemoveProjectMemberResponse(
        removed=True, projectId=project_id, accountId=account_id
    )


@router.get(
    "/resources/{resource_id}/permissions",
    response_model=ListResourcePermissionsResponse,
)
async def list_resource_permissions(
    resource_id: UUID,
    current: Annotated[Session, Depends(get_current_session)],
    use_case: Annotated[
        PermissionAdministration, Depends(get_permission_administration)
    ],
) -> ListResourcePermissionsResponse:
    permissions = await use_case.list_resource_permissions(
        current.account_id, resource_id
    )
    return ListResourcePermissionsResponse(
        permissions=[
            ResourcePermissionContract(
                resourceId=item.resource_id,
                accountId=item.account_id,
                email=item.email,
                role=ListedResourceRole(item.role.value),
                createdAt=item.created_at,
                updatedAt=item.updated_at,
            )
            for item in permissions
        ]
    )


@router.put(
    "/resources/{resource_id}/permissions/{account_id}",
    response_model=SetResourcePermissionResponse,
)
async def set_resource_permission(
    resource_id: UUID,
    account_id: UUID,
    request: SetResourcePermissionRequest,
    current: Annotated[Session, Depends(get_current_session)],
    use_case: Annotated[
        PermissionAdministration, Depends(get_permission_administration)
    ],
    idempotency_key: Annotated[UUID, Header(alias="Idempotency-Key")],
) -> SetResourcePermissionResponse:
    if (request.resourceId, request.accountId) != (resource_id, account_id):
        raise ConflictError(
            "Path and body Resource IDs differ.", "WORKSPACE_REQUEST_MISMATCH"
        )
    permission = await use_case.set_resource_permission(
        current.account_id,
        resource_id,
        account_id,
        PermissionRole(request.role.value),
        str(idempotency_key),
    )
    return SetResourcePermissionResponse(
        resourceId=permission.resource_id,
        accountId=permission.account_id,
        email=permission.email,
        role=ResourceRoleContract(permission.role.value),
        createdAt=permission.created_at,
        updatedAt=permission.updated_at,
    )


@router.delete(
    "/resources/{resource_id}/permissions/{account_id}",
    response_model=RemoveResourcePermissionResponse,
)
async def remove_resource_permission(
    resource_id: UUID,
    account_id: UUID,
    request: RemoveResourcePermissionRequest,
    current: Annotated[Session, Depends(get_current_session)],
    use_case: Annotated[
        PermissionAdministration, Depends(get_permission_administration)
    ],
    idempotency_key: Annotated[UUID, Header(alias="Idempotency-Key")],
) -> RemoveResourcePermissionResponse:
    if (request.resourceId, request.accountId) != (resource_id, account_id):
        raise ConflictError(
            "Path and body Resource IDs differ.", "WORKSPACE_REQUEST_MISMATCH"
        )
    await use_case.remove_resource_permission(
        current.account_id, resource_id, account_id, str(idempotency_key)
    )
    return RemoveResourcePermissionResponse(
        removed=True, resourceId=resource_id, accountId=account_id
    )
