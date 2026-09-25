from __future__ import annotations

import base64
import binascii
import hashlib
import json
import os
from datetime import UTC, datetime
from uuid import UUID, uuid4

from app_core.common.exceptions import (
    ConflictError,
    IdempotencyConflictError,
    NotFoundError,
    PermissionDeniedError,
)
from app_core.permission.domain.access_control import (
    EffectivePermission,
    PermissionRole,
    effective_permission,
)
from app_core.permission.domain.collaboration import (
    CreatedWorkspaceInvitation,
    InvitationAcceptanceExpired,
    ProjectMemberView,
    ResourcePermissionView,
    WorkspaceInvitationView,
    WorkspaceMemberView,
)
from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app_infra.postgres.permission_event_publisher import (
    publish_permission_changed,
)


def decode_invitation_idempotency_encryption_key(value: str | None) -> bytes:
    if not value:
        raise RuntimeError("INVITATION_IDEMPOTENCY_ENCRYPTION_KEY is required.")
    try:
        key = base64.b64decode(value, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise RuntimeError(
            "INVITATION_IDEMPOTENCY_ENCRYPTION_KEY must be valid base64."
        ) from exc
    if len(key) != 32:
        raise RuntimeError(
            "INVITATION_IDEMPOTENCY_ENCRYPTION_KEY must decode to 32 bytes."
        )
    return key


def _idempotency_record_key(
    actor_id: UUID, operation: str, idempotency_key: str
) -> str:
    return f"permission:{operation}:{actor_id}:{idempotency_key}"


def _encrypt_invitation_url(
    key: bytes, record_key: str, fingerprint: str, invitation_url: str
) -> dict[str, str]:
    nonce = os.urandom(12)
    aad = f"{record_key}:{fingerprint}".encode()
    ciphertext = AESGCM(key).encrypt(nonce, invitation_url.encode(), aad)
    return {
        "nonce": base64.b64encode(nonce).decode(),
        "ciphertext": base64.b64encode(ciphertext).decode(),
    }


def _decrypt_invitation_url(
    key: bytes,
    record_key: str,
    fingerprint: str,
    encrypted_url: dict[str, str],
) -> str:
    try:
        nonce = base64.b64decode(encrypted_url["nonce"], validate=True)
        ciphertext = base64.b64decode(encrypted_url["ciphertext"], validate=True)
        aad = f"{record_key}:{fingerprint}".encode()
        return AESGCM(key).decrypt(nonce, ciphertext, aad).decode()
    except (InvalidTag, KeyError, UnicodeDecodeError, ValueError) as exc:
        raise IdempotencyConflictError(
            "The stored invitation response cannot be decrypted."
        ) from exc


class PostgresPermissionAdministrationRepository:
    """Permission mutations, audit and invalidation share the caller transaction."""

    def __init__(
        self, session: AsyncSession, idempotency_encryption_key: bytes
    ) -> None:
        if len(idempotency_encryption_key) != 32:
            raise ValueError("Invitation idempotency AES-GCM key must be 32 bytes.")
        self._session = session
        self._idempotency_encryption_key = idempotency_encryption_key

    async def get_resource_capabilities(
        self, actor_id: UUID, resource_id: UUID
    ) -> EffectivePermission | None:
        row = (
            (
                await self._session.execute(
                    text(
                        "SELECT w.status AS workspace_status, "
                        "p.lifecycle AS project_lifecycle, "
                        "r.lifecycle AS resource_lifecycle, wm.membership_kind, "
                        "pm.role AS project_role, "
                        "rp.role AS resource_role FROM core.resources r "
                        "JOIN core.projects p ON p.project_id=r.project_id "
                        "JOIN core.workspaces w ON w.workspace_id=p.workspace_id "
                        "LEFT JOIN core.workspace_members wm "
                        "ON wm.workspace_id=p.workspace_id AND wm.account_id=:actor_id "
                        "LEFT JOIN core.project_members pm "
                        "ON pm.project_id=p.project_id AND pm.account_id=:actor_id "
                        "LEFT JOIN core.resource_permissions rp "
                        "ON rp.resource_id=r.resource_id AND rp.account_id=:actor_id "
                        "WHERE r.resource_id=:resource_id"
                    ),
                    {"resource_id": resource_id, "actor_id": actor_id},
                )
            )
            .mappings()
            .one_or_none()
        )
        if row is None:
            return None
        project_role = (
            PermissionRole(row["project_role"])
            if row["project_role"] is not None
            else None
        )
        resource_role = (
            PermissionRole(row["resource_role"])
            if row["resource_role"] is not None
            else None
        )
        project_lifecycle = row["project_lifecycle"]
        resource_lifecycle = row["resource_lifecycle"]
        if (
            row["workspace_status"] != "Active"
            or project_lifecycle not in {"Active", "Archived"}
            or resource_lifecycle != "Active"
        ):
            return None
        return effective_permission(
            project_role,
            resource_role,
            workspace_owner=row["membership_kind"] == "Owner",
            workspace_active=row["workspace_status"] == "Active",
            project_active=project_lifecycle in {"Active", "Archived"},
            project_read_only=project_lifecycle == "Archived",
            resource_active=resource_lifecycle == "Active",
        )

    async def create_workspace_invitation(
        self,
        actor_id: UUID,
        workspace_id: UUID,
        target_email: str,
        token_hash: str,
        invitation_url: str,
        expires_at: datetime,
        expires_in_days: int,
        idempotency_key: str,
    ) -> CreatedWorkspaceInvitation:
        fingerprint = _fingerprint(
            "CreateWorkspaceInvitation",
            actor_id,
            {
                "workspaceId": workspace_id,
                "targetEmail": target_email,
                "expiresInDays": expires_in_days,
            },
        )
        operation = "create-invitation"
        record_key = _idempotency_record_key(actor_id, operation, idempotency_key)
        replay = await self._claim_idempotency(
            actor_id, "create-invitation", idempotency_key, fingerprint
        )
        await self._lock_workspace_owner(actor_id, workspace_id)
        if replay is not None:
            invitation_id = replay.get("invitationId")
            encrypted_url = replay.get("encryptedInvitationUrl")
            if not isinstance(invitation_id, str) or not isinstance(
                encrypted_url, dict
            ):
                raise IdempotencyConflictError(
                    "The stored invitation response cannot be replayed."
                )
            original_url = _decrypt_invitation_url(
                self._idempotency_encryption_key,
                record_key,
                fingerprint,
                encrypted_url,
            )
            return CreatedWorkspaceInvitation(
                await self._get_invitation(UUID(invitation_id)), original_url
            )
        now = datetime.now(UTC)
        await self._expire_pending_invites(workspace_id, now)
        existing = (
            await self._session.execute(
                text(
                    "SELECT invitation_id FROM core.invitations "
                    "WHERE workspace_id=:workspace_id AND target_email=:email "
                    "AND project_id IS NULL AND resource_id IS NULL "
                    "AND state='Pending' FOR UPDATE"
                ),
                {"workspace_id": workspace_id, "email": target_email},
            )
        ).scalar_one_or_none()
        if existing is None:
            invitation_id = uuid4()
            await self._session.execute(
                text(
                    "INSERT INTO core.invitations "
                    "(invitation_id, workspace_id, target_email, role, state, "
                    "token_hash, expires_at, created_by) "
                    "VALUES (:id, :workspace_id, :email, 'Member', 'Pending', "
                    ":token_hash, :expires_at, :actor_id)"
                ),
                {
                    "id": invitation_id,
                    "workspace_id": workspace_id,
                    "email": target_email,
                    "token_hash": token_hash,
                    "expires_at": expires_at,
                    "actor_id": actor_id,
                },
            )
            action = "workspace_invitation_created"
        else:
            invitation_id = existing
            await self._session.execute(
                text(
                    "UPDATE core.invitations SET token_hash=:token_hash, "
                    "expires_at=:expires_at, created_by=:actor_id, "
                    "created_at=:now WHERE invitation_id=:id"
                ),
                {
                    "token_hash": token_hash,
                    "expires_at": expires_at,
                    "actor_id": actor_id,
                    "now": now,
                    "id": invitation_id,
                },
            )
            action = "workspace_invitation_rotated"
        await self._record_audit(
            actor_id,
            action,
            workspace_id=workspace_id,
            target_ref={"invitationId": str(invitation_id)},
            metadata={"targetEmail": target_email},
        )
        invitation = await self._get_invitation(invitation_id)
        await self._complete_invitation_idempotency(
            record_key,
            fingerprint,
            invitation_id,
            _encrypt_invitation_url(
                self._idempotency_encryption_key,
                record_key,
                fingerprint,
                invitation_url,
            ),
        )
        return CreatedWorkspaceInvitation(invitation, invitation_url)

    async def list_workspace_members(
        self, actor_id: UUID, workspace_id: UUID
    ) -> list[WorkspaceMemberView]:
        await self._require_workspace_owner(actor_id, workspace_id, lock=False)
        rows = (
            await self._session.execute(
                text(
                    "SELECT m.account_id, COALESCE(a.primary_email, "
                    "a.normalized_email, '') AS email, m.membership_kind, m.created_at "
                    "FROM core.workspace_members AS m "
                    "JOIN auth.accounts AS a ON a.account_id=m.account_id "
                    "WHERE m.workspace_id=:workspace_id "
                    "ORDER BY m.membership_kind DESC, m.created_at, m.account_id"
                ),
                {"workspace_id": workspace_id},
            )
        ).mappings()
        return [
            WorkspaceMemberView(
                workspace_id,
                row["account_id"],
                row["email"],
                row["membership_kind"],
                row["created_at"],
            )
            for row in rows
        ]

    async def list_workspace_invitations(
        self, actor_id: UUID, workspace_id: UUID
    ) -> list[WorkspaceInvitationView]:
        await self._require_workspace_owner(actor_id, workspace_id, lock=True)
        await self._expire_pending_invites(workspace_id, datetime.now(UTC))
        rows = (
            await self._session.execute(
                text(
                    "SELECT invitation_id, workspace_id, target_email, "
                    "target_account_id, role, state, expires_at, created_by, "
                    "created_at, accepted_at FROM core.invitations "
                    "WHERE workspace_id=:workspace_id AND project_id IS NULL "
                    "AND resource_id IS NULL ORDER BY created_at DESC"
                ),
                {"workspace_id": workspace_id},
            )
        ).mappings()
        return [_invitation_view(row) for row in rows]

    async def accept_workspace_invitation(
        self, actor_id: UUID, token_hash: str
    ) -> WorkspaceMemberView | InvitationAcceptanceExpired:
        invite = (
            await self._session.execute(
                text(
                    "SELECT invitation_id, workspace_id FROM core.invitations "
                    "WHERE token_hash=:token_hash"
                ),
                {"token_hash": token_hash},
            )
        ).one_or_none()
        if invite is None:
            raise NotFoundError("Invitation is invalid.", "INVITATION_INVALID")
        invitation_id, workspace_id = invite
        await self._lock_workspace(workspace_id)
        row = (
            (
                await self._session.execute(
                    text(
                        "SELECT * FROM core.invitations WHERE invitation_id=:id "
                        "FOR UPDATE"
                    ),
                    {"id": invitation_id},
                )
            )
            .mappings()
            .one_or_none()
        )
        if row is None or row["token_hash"] != token_hash:
            raise NotFoundError("Invitation is invalid.", "INVITATION_INVALID")
        if row["project_id"] is not None or row["resource_id"] is not None:
            raise ConflictError(
                "This invitation scope is not supported by workspace acceptance.",
                "INVITATION_SCOPE_UNSUPPORTED",
            )
        if row["state"] == "Accepted":
            if row["target_account_id"] != actor_id:
                raise PermissionDeniedError(
                    "Invitation belongs to another account.",
                    "INVITATION_EMAIL_MISMATCH",
                )
            return await self._workspace_member_view(workspace_id, actor_id)
        if row["state"] == "Expired":
            return InvitationAcceptanceExpired()
        if row["state"] == "Revoked":
            raise ConflictError("Invitation has been revoked.", "INVITATION_REVOKED")
        now = datetime.now(UTC)
        if row["expires_at"] <= now:
            await self._expire_invitation(row, now)
            return InvitationAcceptanceExpired()
        await self._validate_invitation_target(actor_id, row)
        if not await self._invitation_creator_is_owner(workspace_id, row["created_by"]):
            raise ConflictError(
                "Invitation creator no longer manages this Workspace.",
                "INVITATION_CREATOR_UNAUTHORIZED",
            )
        await self._session.execute(
            text(
                "INSERT INTO core.workspace_members "
                "(workspace_id, account_id, membership_kind) "
                "VALUES (:workspace_id, :account_id, 'Member') "
                "ON CONFLICT (workspace_id, account_id) DO NOTHING"
            ),
            {"workspace_id": workspace_id, "account_id": actor_id},
        )
        await self._session.execute(
            text(
                "UPDATE core.invitations SET state='Accepted', accepted_at=:now, "
                "target_account_id=:account_id WHERE invitation_id=:id"
            ),
            {"now": now, "account_id": actor_id, "id": invitation_id},
        )
        await self._record_audit(
            actor_id,
            "workspace_invitation_accepted",
            workspace_id=workspace_id,
            target_ref={"accountId": str(actor_id)},
            metadata={"invitationId": str(invitation_id)},
        )
        await self._publish_permission_change(
            "workspace",
            workspace_id,
            workspace_id,
            actor_id,
            "member_added",
            "Member",
        )
        return await self._workspace_member_view(workspace_id, actor_id)

    async def _validate_invitation_target(self, actor_id: UUID, row) -> None:
        account = (
            await self._session.execute(
                text(
                    "SELECT normalized_email FROM auth.accounts "
                    "WHERE account_id=:account_id AND status='Active' FOR UPDATE"
                ),
                {"account_id": actor_id},
            )
        ).scalar_one_or_none()
        if account is None or account.casefold() != row["target_email"].casefold():
            raise PermissionDeniedError(
                "Invitation email does not match the active account.",
                "INVITATION_EMAIL_MISMATCH",
            )
        if row["target_account_id"] not in {None, actor_id}:
            raise PermissionDeniedError(
                "Invitation belongs to another account.",
                "INVITATION_EMAIL_MISMATCH",
            )

    async def _invitation_creator_is_owner(
        self, workspace_id: UUID, creator_id: UUID
    ) -> bool:
        return bool(
            await self._session.scalar(
                text(
                    "SELECT EXISTS (SELECT 1 FROM core.workspace_members "
                    "WHERE workspace_id=:workspace_id AND account_id=:creator_id "
                    "AND membership_kind='Owner')"
                ),
                {"workspace_id": workspace_id, "creator_id": creator_id},
            )
        )

    async def revoke_workspace_invitation(
        self,
        actor_id: UUID,
        workspace_id: UUID,
        invitation_id: UUID,
        idempotency_key: str,
    ) -> WorkspaceInvitationView:
        await self._claim_idempotency(
            actor_id,
            "revoke-invitation",
            idempotency_key,
            _fingerprint(
                "RevokeWorkspaceInvitation",
                actor_id,
                {"workspaceId": workspace_id, "invitationId": invitation_id},
            ),
        )
        await self._lock_workspace_owner(actor_id, workspace_id)
        row = (
            (
                await self._session.execute(
                    text(
                        "SELECT * FROM core.invitations WHERE invitation_id=:id "
                        "AND workspace_id=:workspace_id AND project_id IS NULL "
                        "AND resource_id IS NULL FOR UPDATE"
                    ),
                    {"id": invitation_id, "workspace_id": workspace_id},
                )
            )
            .mappings()
            .one_or_none()
        )
        if row is None:
            raise NotFoundError("Invitation not found.", "INVITATION_NOT_FOUND")
        if row["state"] == "Accepted":
            raise ConflictError(
                "An accepted invitation cannot be revoked.",
                "INVITATION_STATE_CONFLICT",
            )
        if row["state"] == "Pending":
            now = datetime.now(UTC)
            if row["expires_at"] <= now:
                await self._expire_invitation(row, now)
            else:
                await self._session.execute(
                    text(
                        "UPDATE core.invitations SET state='Revoked', revoked_at=:now "
                        "WHERE invitation_id=:id"
                    ),
                    {"now": now, "id": invitation_id},
                )
                await self._record_audit(
                    actor_id,
                    "workspace_invitation_revoked",
                    workspace_id=workspace_id,
                    target_ref={"invitationId": str(invitation_id)},
                )
        return await self._get_invitation(invitation_id)

    async def remove_workspace_member(
        self,
        actor_id: UUID,
        workspace_id: UUID,
        account_id: UUID,
        idempotency_key: str,
    ) -> None:
        await self._claim_idempotency(
            actor_id,
            "remove-workspace-member",
            idempotency_key,
            _fingerprint(
                "RemoveWorkspaceMember",
                actor_id,
                {"workspaceId": workspace_id, "accountId": account_id},
            ),
        )
        await self._lock_workspace_owner(actor_id, workspace_id)
        row = (
            await self._session.execute(
                text(
                    "SELECT membership_kind FROM core.workspace_members "
                    "WHERE workspace_id=:workspace_id AND account_id=:account_id "
                    "FOR UPDATE"
                ),
                {"workspace_id": workspace_id, "account_id": account_id},
            )
        ).scalar_one_or_none()
        if row is None:
            return
        if row == "Owner":
            raise ConflictError(
                "Workspace Owner must be transferred before removal.",
                "WORKSPACE_OWNER_PROTECTED",
            )
        await self._session.execute(
            text(
                "DELETE FROM core.workspace_members WHERE workspace_id=:workspace_id "
                "AND account_id=:account_id AND membership_kind='Member'"
            ),
            {"workspace_id": workspace_id, "account_id": account_id},
        )
        await self._record_audit(
            actor_id,
            "workspace_member_removed",
            workspace_id=workspace_id,
            target_ref={"accountId": str(account_id)},
        )
        await self._publish_permission_change(
            "workspace",
            workspace_id,
            workspace_id,
            account_id,
            "member_removed",
            "Member",
        )

    async def list_project_members(
        self, actor_id: UUID, project_id: UUID
    ) -> list[ProjectMemberView]:
        _, role = await self._project_context(actor_id, project_id, lock=False)
        self._require_project_admin(role)
        rows = (
            await self._session.execute(
                text(
                    "SELECT pm.project_id, pm.account_id, "
                    "COALESCE(a.primary_email, a.normalized_email, '') AS email, "
                    "pm.role, pm.membership_kind, pm.created_at, pm.updated_at "
                    "FROM core.project_members pm "
                    "JOIN auth.accounts a ON a.account_id=pm.account_id "
                    "WHERE pm.project_id=:project_id ORDER BY pm.role, pm.created_at"
                ),
                {"project_id": project_id},
            )
        ).mappings()
        return [_project_member_view(row) for row in rows]

    async def set_project_member_role(
        self,
        actor_id: UUID,
        project_id: UUID,
        account_id: UUID,
        role: PermissionRole,
        idempotency_key: str,
    ) -> ProjectMemberView:
        await self._claim_idempotency(
            actor_id,
            "set-project-member-role",
            idempotency_key,
            _fingerprint(
                "SetProjectMemberRole",
                actor_id,
                {"projectId": project_id, "accountId": account_id, "role": role},
            ),
        )
        workspace_id, actor_role = await self._project_context(
            actor_id, project_id, lock=True
        )
        self._require_project_admin(actor_role)
        existing_role = await self._get_project_member_role(
            project_id, account_id, lock=True
        )
        if role is PermissionRole.OWNER and actor_role is not PermissionRole.OWNER:
            raise PermissionDeniedError(
                "Only a Project Owner can grant Project Owner.",
                "PROJECT_OWNER_REQUIRED",
            )
        if existing_role is PermissionRole.OWNER and role is not PermissionRole.OWNER:
            if actor_role is not PermissionRole.OWNER:
                raise PermissionDeniedError(
                    "Only a Project Owner can change another Project Owner.",
                    "PROJECT_OWNER_REQUIRED",
                )
            if await self._count_project_owners(project_id) <= 1:
                raise ConflictError(
                    "Project must retain at least one Owner.",
                    "PROJECT_OWNER_PROTECTED",
                )
        await self._require_active_account(account_id)
        now = datetime.now(UTC)
        await self._session.execute(
            text(
                "INSERT INTO core.project_members "
                "(project_id, account_id, role, membership_kind, created_at, "
                "updated_at) "
                "VALUES (:project_id, :account_id, :role, :kind, :now, :now) "
                "ON CONFLICT (project_id, account_id) DO UPDATE SET "
                "role=EXCLUDED.role, membership_kind=EXCLUDED.membership_kind, "
                "updated_at=EXCLUDED.updated_at"
            ),
            {
                "project_id": project_id,
                "account_id": account_id,
                "role": role.value,
                "kind": "Owner" if role is PermissionRole.OWNER else "Member",
                "now": now,
            },
        )
        if existing_role is not role:
            await self._record_audit(
                actor_id,
                "project_member_role_changed",
                workspace_id=workspace_id,
                project_id=project_id,
                target_ref={"accountId": str(account_id)},
                metadata={
                    "previousRole": existing_role.value if existing_role else None,
                    "role": role.value,
                },
            )
            await self._publish_permission_change(
                "project",
                project_id,
                workspace_id,
                account_id,
                "project_role_changed",
                role.value,
            )
        return await self._project_member_view(project_id, account_id)

    async def remove_project_member(
        self,
        actor_id: UUID,
        project_id: UUID,
        account_id: UUID,
        idempotency_key: str,
    ) -> None:
        await self._claim_idempotency(
            actor_id,
            "remove-project-member",
            idempotency_key,
            _fingerprint(
                "RemoveProjectMember",
                actor_id,
                {"projectId": project_id, "accountId": account_id},
            ),
        )
        workspace_id, actor_role = await self._project_context(
            actor_id, project_id, lock=True
        )
        self._require_project_admin(actor_role)
        existing_role = await self._get_project_member_role(
            project_id, account_id, lock=True
        )
        if existing_role is None:
            return
        if existing_role is PermissionRole.OWNER:
            if actor_role is not PermissionRole.OWNER:
                raise PermissionDeniedError(
                    "Only a Project Owner can remove another Project Owner.",
                    "PROJECT_OWNER_REQUIRED",
                )
            if await self._count_project_owners(project_id) <= 1:
                raise ConflictError(
                    "Project must retain at least one Owner.",
                    "PROJECT_OWNER_PROTECTED",
                )
        await self._session.execute(
            text(
                "DELETE FROM core.project_members WHERE project_id=:project_id "
                "AND account_id=:account_id"
            ),
            {"project_id": project_id, "account_id": account_id},
        )
        await self._record_audit(
            actor_id,
            "project_member_removed",
            workspace_id=workspace_id,
            project_id=project_id,
            target_ref={"accountId": str(account_id)},
            metadata={"role": existing_role.value},
        )
        await self._publish_permission_change(
            "project",
            project_id,
            workspace_id,
            account_id,
            "project_member_removed",
            None,
        )

    async def list_resource_permissions(
        self, actor_id: UUID, resource_id: UUID
    ) -> list[ResourcePermissionView]:
        workspace_id, project_id, role = await self._resource_context(
            actor_id, resource_id, lock=False
        )
        self._require_project_admin(role)
        rows = (
            await self._session.execute(
                text(
                    "SELECT rp.resource_id, rp.account_id, "
                    "COALESCE(a.primary_email, a.normalized_email, '') AS email, "
                    "rp.role, rp.created_at, rp.updated_at "
                    "FROM core.resource_permissions rp "
                    "JOIN auth.accounts a ON a.account_id=rp.account_id "
                    "WHERE rp.resource_id=:resource_id ORDER BY rp.created_at"
                ),
                {"resource_id": resource_id},
            )
        ).mappings()
        return [_resource_permission_view(row) for row in rows]

    async def set_resource_permission(
        self,
        actor_id: UUID,
        resource_id: UUID,
        account_id: UUID,
        role: PermissionRole,
        idempotency_key: str,
    ) -> ResourcePermissionView:
        await self._claim_idempotency(
            actor_id,
            "set-resource-permission",
            idempotency_key,
            _fingerprint(
                "SetResourcePermission",
                actor_id,
                {"resourceId": resource_id, "accountId": account_id, "role": role},
            ),
        )
        workspace_id, project_id, actor_role = await self._resource_context(
            actor_id, resource_id, lock=True
        )
        self._require_project_admin(actor_role)
        if role is PermissionRole.OWNER and actor_role is not PermissionRole.OWNER:
            raise PermissionDeniedError(
                "Only a Project Owner can grant Resource Owner.",
                "PROJECT_OWNER_REQUIRED",
            )
        await self._require_active_account(account_id)
        existing = await self._session.scalar(
            text(
                "SELECT role FROM core.resource_permissions "
                "WHERE resource_id=:resource_id AND account_id=:account_id FOR UPDATE"
            ),
            {"resource_id": resource_id, "account_id": account_id},
        )
        now = datetime.now(UTC)
        await self._session.execute(
            text(
                "INSERT INTO core.resource_permissions "
                "(resource_id, account_id, role, created_at, updated_at) "
                "VALUES (:resource_id, :account_id, :role, :now, :now) "
                "ON CONFLICT (resource_id, account_id) DO UPDATE SET "
                "role=EXCLUDED.role, updated_at=EXCLUDED.updated_at"
            ),
            {
                "resource_id": resource_id,
                "account_id": account_id,
                "role": role.value,
                "now": now,
            },
        )
        if existing != role.value:
            await self._record_audit(
                actor_id,
                "resource_permission_changed",
                workspace_id=workspace_id,
                project_id=project_id,
                resource_id=resource_id,
                target_ref={"accountId": str(account_id)},
                metadata={"previousRole": existing, "role": role.value},
            )
            await self._publish_permission_change(
                "resource",
                resource_id,
                workspace_id,
                account_id,
                "resource_permission_changed",
                role.value,
            )
        return await self._resource_permission_view(resource_id, account_id)

    async def remove_resource_permission(
        self,
        actor_id: UUID,
        resource_id: UUID,
        account_id: UUID,
        idempotency_key: str,
    ) -> None:
        await self._claim_idempotency(
            actor_id,
            "remove-resource-permission",
            idempotency_key,
            _fingerprint(
                "RemoveResourcePermission",
                actor_id,
                {"resourceId": resource_id, "accountId": account_id},
            ),
        )
        workspace_id, project_id, actor_role = await self._resource_context(
            actor_id, resource_id, lock=True
        )
        self._require_project_admin(actor_role)
        existing = await self._session.scalar(
            text(
                "DELETE FROM core.resource_permissions "
                "WHERE resource_id=:resource_id AND account_id=:account_id "
                "RETURNING role"
            ),
            {"resource_id": resource_id, "account_id": account_id},
        )
        if existing is None:
            return
        await self._record_audit(
            actor_id,
            "resource_permission_removed",
            workspace_id=workspace_id,
            project_id=project_id,
            resource_id=resource_id,
            target_ref={"accountId": str(account_id)},
            metadata={"role": existing},
        )
        await self._publish_permission_change(
            "resource",
            resource_id,
            workspace_id,
            account_id,
            "resource_permission_removed",
            None,
        )

    async def _lock_workspace_owner(self, actor_id: UUID, workspace_id: UUID) -> None:
        await self._lock_workspace(workspace_id)
        await self._require_workspace_owner(actor_id, workspace_id, lock=False)

    async def _lock_workspace(self, workspace_id: UUID) -> None:
        status = await self._session.scalar(
            text(
                "SELECT status FROM core.workspaces WHERE workspace_id=:id FOR UPDATE"
            ),
            {"id": workspace_id},
        )
        if status is None or status == "Deleted":
            raise NotFoundError("Workspace not found.", "WORKSPACE_NOT_FOUND")
        if status != "Active":
            raise ConflictError(
                "Workspace is not active.", "WORKSPACE_LIFECYCLE_CONFLICT"
            )

    async def _require_workspace_owner(
        self, actor_id: UUID, workspace_id: UUID, *, lock: bool
    ) -> None:
        statement = (
            "SELECT membership_kind FROM core.workspace_members "
            "WHERE workspace_id=:workspace_id AND account_id=:actor_id"
        )
        if lock:
            statement += " FOR UPDATE"
        role = await self._session.scalar(
            text(statement), {"workspace_id": workspace_id, "actor_id": actor_id}
        )
        if role != "Owner":
            raise PermissionDeniedError(
                "Only the Workspace Owner can manage Workspace membership.",
                "WORKSPACE_PERMISSION_DENIED",
            )

    async def _project_context(
        self, actor_id: UUID, project_id: UUID, *, lock: bool
    ) -> tuple[UUID, PermissionRole | None]:
        workspace_id = await self._session.scalar(
            text("SELECT workspace_id FROM core.projects WHERE project_id=:id"),
            {"id": project_id},
        )
        if workspace_id is None:
            raise NotFoundError("Project not found.", "PROJECT_NOT_FOUND")
        if lock:
            await self._lock_workspace(workspace_id)
            row = (
                await self._session.execute(
                    text(
                        "SELECT lifecycle FROM core.projects WHERE project_id=:id "
                        "FOR UPDATE"
                    ),
                    {"id": project_id},
                )
            ).one_or_none()
            if row is None:
                raise NotFoundError("Project not found.", "PROJECT_NOT_FOUND")
            if row.lifecycle != "Active":
                raise ConflictError(
                    "Project is not active.", "PROJECT_LIFECYCLE_CONFLICT"
                )
        workspace_owner = await self._session.scalar(
            text(
                "SELECT EXISTS (SELECT 1 FROM core.workspace_members "
                "WHERE workspace_id=:workspace_id AND account_id=:actor_id "
                "AND membership_kind='Owner')"
            ),
            {"workspace_id": workspace_id, "actor_id": actor_id},
        )
        project_role = await self._session.scalar(
            text(
                "SELECT role FROM core.project_members "
                "WHERE project_id=:project_id AND account_id=:actor_id"
                + (" FOR UPDATE" if lock else "")
            ),
            {"project_id": project_id, "actor_id": actor_id},
        )
        role = effective_permission(
            PermissionRole(project_role) if project_role is not None else None,
            workspace_owner=bool(workspace_owner),
        ).role
        return workspace_id, role

    async def _resource_context(
        self, actor_id: UUID, resource_id: UUID, *, lock: bool
    ) -> tuple[UUID, UUID, PermissionRole | None]:
        row = (
            await self._session.execute(
                text(
                    "SELECT p.workspace_id, p.project_id FROM core.resources r "
                    "JOIN core.projects p ON p.project_id=r.project_id "
                    "WHERE r.resource_id=:resource_id"
                ),
                {"resource_id": resource_id},
            )
        ).one_or_none()
        if row is None:
            raise NotFoundError("Resource not found.", "RESOURCE_NOT_FOUND")
        workspace_id, project_id = row
        if lock:
            await self._lock_workspace(workspace_id)
            await self._session.execute(
                text(
                    "SELECT project_id FROM core.projects "
                    "WHERE project_id=:id FOR UPDATE"
                ),
                {"id": project_id},
            )
            await self._session.execute(
                text(
                    "SELECT resource_id FROM core.resources "
                    "WHERE resource_id=:id FOR UPDATE"
                ),
                {"id": resource_id},
            )
        workspace_owner = await self._is_workspace_owner(actor_id, workspace_id)
        project_role_value = await self._session.scalar(
            text(
                "SELECT role FROM core.project_members "
                "WHERE project_id=:project_id AND account_id=:actor_id"
            ),
            {"project_id": project_id, "actor_id": actor_id},
        )
        project_role = (
            PermissionRole(project_role_value)
            if project_role_value is not None
            else None
        )
        if lock:
            row_role = await self._session.scalar(
                text(
                    "SELECT role FROM core.resource_permissions "
                    "WHERE resource_id=:resource_id AND account_id=:actor_id FOR UPDATE"
                ),
                {"resource_id": resource_id, "actor_id": actor_id},
            )
        else:
            row_role = await self._session.scalar(
                text(
                    "SELECT role FROM core.resource_permissions "
                    "WHERE resource_id=:resource_id AND account_id=:actor_id"
                ),
                {"resource_id": resource_id, "actor_id": actor_id},
            )
        resource_override = PermissionRole(row_role) if row_role is not None else None
        effective = effective_permission(
            project_role,
            resource_override,
            workspace_owner=workspace_owner,
        ).role
        return workspace_id, project_id, effective

    async def _is_workspace_owner(self, actor_id: UUID, workspace_id: UUID) -> bool:
        return bool(
            await self._session.scalar(
                text(
                    "SELECT EXISTS (SELECT 1 FROM core.workspace_members "
                    "WHERE workspace_id=:workspace_id AND account_id=:actor_id "
                    "AND membership_kind='Owner')"
                ),
                {"workspace_id": workspace_id, "actor_id": actor_id},
            )
        )

    @staticmethod
    def _require_project_admin(role: PermissionRole | None) -> None:
        if role not in {PermissionRole.OWNER, PermissionRole.MANAGE}:
            raise PermissionDeniedError(
                "Project Owner or Manage capability is required.",
                "WORKSPACE_PERMISSION_DENIED",
            )

    async def _get_project_member_role(
        self, project_id: UUID, account_id: UUID, *, lock: bool
    ) -> PermissionRole | None:
        role = await self._session.scalar(
            text(
                "SELECT role FROM core.project_members "
                "WHERE project_id=:project_id AND account_id=:account_id"
                + (" FOR UPDATE" if lock else "")
            ),
            {"project_id": project_id, "account_id": account_id},
        )
        return PermissionRole(role) if role is not None else None

    async def _count_project_owners(self, project_id: UUID) -> int:
        count = await self._session.scalar(
            text(
                "SELECT count(*) FROM core.project_members "
                "WHERE project_id=:project_id AND role='Owner'"
            ),
            {"project_id": project_id},
        )
        return int(count or 0)

    async def _require_active_account(self, account_id: UUID) -> None:
        status = await self._session.scalar(
            text("SELECT status FROM auth.accounts WHERE account_id=:id FOR UPDATE"),
            {"id": account_id},
        )
        if status != "Active":
            raise ConflictError(
                "Target account is not Active.", "TARGET_ACCOUNT_INACTIVE"
            )

    async def _workspace_member_view(
        self, workspace_id: UUID, account_id: UUID
    ) -> WorkspaceMemberView:
        row = (
            (
                await self._session.execute(
                    text(
                        "SELECT m.account_id, COALESCE(a.primary_email, "
                        "a.normalized_email, '') AS email, m.membership_kind, "
                        "m.created_at "
                        "FROM core.workspace_members m "
                        "JOIN auth.accounts a ON a.account_id=m.account_id "
                        "WHERE m.workspace_id=:workspace_id "
                        "AND m.account_id=:account_id"
                    ),
                    {"workspace_id": workspace_id, "account_id": account_id},
                )
            )
            .mappings()
            .one()
        )
        return WorkspaceMemberView(
            workspace_id,
            row["account_id"],
            row["email"],
            row["membership_kind"],
            row["created_at"],
        )

    async def _project_member_view(
        self, project_id: UUID, account_id: UUID
    ) -> ProjectMemberView:
        row = (
            (
                await self._session.execute(
                    text(
                        "SELECT pm.project_id, pm.account_id, "
                        "COALESCE(a.primary_email, a.normalized_email, '') AS email, "
                        "pm.role, pm.membership_kind, pm.created_at, pm.updated_at "
                        "FROM core.project_members pm "
                        "JOIN auth.accounts a ON a.account_id=pm.account_id "
                        "WHERE pm.project_id=:project_id AND pm.account_id=:account_id"
                    ),
                    {"project_id": project_id, "account_id": account_id},
                )
            )
            .mappings()
            .one()
        )
        return _project_member_view(row)

    async def _resource_permission_view(
        self, resource_id: UUID, account_id: UUID
    ) -> ResourcePermissionView:
        row = (
            (
                await self._session.execute(
                    text(
                        "SELECT rp.resource_id, rp.account_id, "
                        "COALESCE(a.primary_email, a.normalized_email, '') AS email, "
                        "rp.role, rp.created_at, rp.updated_at "
                        "FROM core.resource_permissions rp "
                        "JOIN auth.accounts a ON a.account_id=rp.account_id "
                        "WHERE rp.resource_id=:resource_id "
                        "AND rp.account_id=:account_id"
                    ),
                    {"resource_id": resource_id, "account_id": account_id},
                )
            )
            .mappings()
            .one()
        )
        return _resource_permission_view(row)

    async def _get_invitation(self, invitation_id: UUID) -> WorkspaceInvitationView:
        row = (
            (
                await self._session.execute(
                    text(
                        "SELECT invitation_id, workspace_id, target_email, "
                        "target_account_id, role, state, expires_at, created_by, "
                        "created_at, accepted_at FROM core.invitations "
                        "WHERE invitation_id=:id"
                    ),
                    {"id": invitation_id},
                )
            )
            .mappings()
            .one()
        )
        return _invitation_view(row)

    async def _expire_pending_invites(self, workspace_id: UUID, now: datetime) -> None:
        rows = (
            await self._session.execute(
                text(
                    "UPDATE core.invitations SET state='Expired' "
                    "WHERE workspace_id=:workspace_id AND state='Pending' "
                    "AND expires_at<=:now RETURNING invitation_id, target_email"
                ),
                {"workspace_id": workspace_id, "now": now},
            )
        ).mappings()
        for row in rows:
            await self._record_audit(
                None,
                "workspace_invitation_expired",
                workspace_id=workspace_id,
                target_ref={"invitationId": str(row["invitation_id"])},
                metadata={"targetEmail": row["target_email"]},
            )

    async def _expire_invitation(self, row, now: datetime) -> None:
        await self._session.execute(
            text(
                "UPDATE core.invitations SET state='Expired' "
                "WHERE invitation_id=:id AND state='Pending'"
            ),
            {"id": row["invitation_id"]},
        )
        await self._record_audit(
            None,
            "workspace_invitation_expired",
            workspace_id=row["workspace_id"],
            target_ref={"invitationId": str(row["invitation_id"])},
            metadata={"targetEmail": row["target_email"], "expiredAt": now.isoformat()},
        )

    async def _claim_idempotency(
        self,
        actor_id: UUID,
        operation: str,
        idempotency_key: str,
        fingerprint: str,
    ) -> dict[str, object] | None:
        if not idempotency_key or len(idempotency_key) > 200:
            raise IdempotencyConflictError("Invalid Idempotency-Key.")
        key = _idempotency_record_key(actor_id, operation, idempotency_key)
        inserted = await self._session.scalar(
            text(
                "INSERT INTO integration.idempotency_records "
                "(idempotency_key, response) VALUES (:key, :response) "
                "ON CONFLICT (idempotency_key) DO NOTHING "
                "RETURNING idempotency_key"
            ),
            {
                "key": key,
                "response": json.dumps({"fingerprint": fingerprint}),
            },
        )
        if inserted is not None:
            return None
        response = await self._session.scalar(
            text(
                "SELECT response FROM integration.idempotency_records "
                "WHERE idempotency_key=:key FOR UPDATE"
            ),
            {"key": key},
        )
        stored = json.loads(response) if response else None
        if not isinstance(stored, dict) or stored.get("fingerprint") != fingerprint:
            raise IdempotencyConflictError(
                "Idempotency key was used for a different Permission mutation."
            )
        return stored

    async def _complete_invitation_idempotency(
        self,
        record_key: str,
        fingerprint: str,
        invitation_id: UUID,
        encrypted_invitation_url: dict[str, str],
    ) -> None:
        response = json.dumps(
            {
                "fingerprint": fingerprint,
                "invitationId": str(invitation_id),
                "encryptedInvitationUrl": encrypted_invitation_url,
            }
        )
        retained_key = await self._session.scalar(
            text(
                "UPDATE integration.idempotency_records SET response=:response "
                "WHERE idempotency_key=:key RETURNING idempotency_key"
            ),
            {"key": record_key, "response": response},
        )
        if retained_key is None:
            raise IdempotencyConflictError(
                "Invitation idempotency record was not retained."
            )

    async def _record_audit(
        self,
        actor_id: UUID | None,
        action: str,
        *,
        workspace_id: UUID | None = None,
        project_id: UUID | None = None,
        resource_id: UUID | None = None,
        target_ref: dict[str, str] | None = None,
        metadata: dict[str, object] | None = None,
    ) -> None:
        await self._session.execute(
            text(
                "INSERT INTO audit.entries "
                "(audit_id, actor_type, actor_id, action, workspace_id, project_id, "
                "resource_id, target_ref, metadata) "
                "VALUES (:id, :actor_type, :actor_id, :action, :workspace_id, "
                ":project_id, :resource_id, CAST(:target_ref AS jsonb), "
                "CAST(:metadata AS jsonb))"
            ),
            {
                "id": uuid4(),
                "actor_type": "Account" if actor_id is not None else "System",
                "actor_id": actor_id,
                "action": action,
                "workspace_id": workspace_id,
                "project_id": project_id,
                "resource_id": resource_id,
                "target_ref": json.dumps(target_ref or {}),
                "metadata": json.dumps(metadata or {}),
            },
        )

    async def _publish_permission_change(
        self,
        scope_type: str,
        scope_id: UUID,
        workspace_id: UUID,
        account_id: UUID | None,
        action: str,
        role: str | None,
    ) -> None:
        await publish_permission_changed(
            self._session,
            scope_type=scope_type,
            scope_id=scope_id,
            workspace_id=workspace_id,
            account_id=account_id,
            action=action,
            role=role,
        )


def _fingerprint(action: str, actor_id: UUID, values: dict[str, object]) -> str:
    canonical = {"action": action, "actorId": str(actor_id)}
    canonical.update(
        {
            key: str(value.value if isinstance(value, PermissionRole) else value)
            for key, value in values.items()
        }
    )
    return hashlib.sha256(
        json.dumps(canonical, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _invitation_view(row) -> WorkspaceInvitationView:
    return WorkspaceInvitationView(
        invitation_id=row["invitation_id"],
        workspace_id=row["workspace_id"],
        target_email=row["target_email"],
        target_account_id=row["target_account_id"],
        role=row["role"],
        state=row["state"],
        expires_at=row["expires_at"],
        created_by=row["created_by"],
        created_at=row["created_at"],
        accepted_at=row["accepted_at"],
    )


def _project_member_view(row) -> ProjectMemberView:
    return ProjectMemberView(
        project_id=row["project_id"],
        account_id=row["account_id"],
        email=row["email"],
        role=PermissionRole(row["role"]),
        membership_kind=row["membership_kind"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def _resource_permission_view(row) -> ResourcePermissionView:
    return ResourcePermissionView(
        resource_id=row["resource_id"],
        account_id=row["account_id"],
        email=row["email"],
        role=PermissionRole(row["role"]),
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )
