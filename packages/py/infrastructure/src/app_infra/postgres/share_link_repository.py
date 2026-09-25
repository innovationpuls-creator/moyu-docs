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
    PermissionRole,
    effective_permission,
)
from app_core.permission.domain.share_link import (
    AnonymousShareGrant,
    CreatedShareLink,
    ShareCapability,
    ShareLinkStatus,
    ShareLinkView,
)
from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


def decode_share_link_idempotency_encryption_key(value: str | None) -> bytes:
    if not value:
        raise RuntimeError("SHARE_LINK_IDEMPOTENCY_ENCRYPTION_KEY is required.")
    try:
        key = base64.b64decode(value, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise RuntimeError(
            "SHARE_LINK_IDEMPOTENCY_ENCRYPTION_KEY must be valid base64."
        ) from exc
    if len(key) != 32:
        raise RuntimeError(
            "SHARE_LINK_IDEMPOTENCY_ENCRYPTION_KEY must decode to 32 bytes."
        )
    return key


def _record_key(actor_id: UUID, operation: str, idempotency_key: str) -> str:
    return f"permission:{operation}:{actor_id}:{idempotency_key}"


def _fingerprint(action: str, actor_id: UUID, values: dict[str, object]) -> str:
    canonical = {"action": action, "actorId": str(actor_id)}
    canonical.update({key: str(value) for key, value in values.items()})
    return hashlib.sha256(
        json.dumps(canonical, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _encrypt_share_url(
    key: bytes, record_key: str, fingerprint: str, share_url: str
) -> dict[str, str]:
    nonce = os.urandom(12)
    aad = f"{record_key}:{fingerprint}".encode()
    ciphertext = AESGCM(key).encrypt(nonce, share_url.encode(), aad)
    return {
        "nonce": base64.b64encode(nonce).decode(),
        "ciphertext": base64.b64encode(ciphertext).decode(),
    }


def _decrypt_share_url(
    key: bytes,
    record_key: str,
    fingerprint: str,
    encrypted_url: dict[str, str],
) -> str:
    try:
        nonce = base64.b64decode(encrypted_url["nonce"], validate=True)
        ciphertext = base64.b64decode(encrypted_url["ciphertext"], validate=True)
        return (
            AESGCM(key)
            .decrypt(nonce, ciphertext, f"{record_key}:{fingerprint}".encode())
            .decode()
        )
    except (InvalidTag, KeyError, UnicodeDecodeError, ValueError) as exc:
        raise IdempotencyConflictError(
            "The stored share response cannot be decrypted."
        ) from exc


class PostgresShareLinkRepository:
    """Permission-owned Share Link state; caller owns the transaction boundary."""

    def __init__(
        self, session: AsyncSession, idempotency_encryption_key: bytes
    ) -> None:
        if len(idempotency_encryption_key) != 32:
            raise ValueError("Share idempotency AES-GCM key must be 32 bytes.")
        self._session = session
        self._idempotency_encryption_key = idempotency_encryption_key

    async def create_share_link(
        self,
        actor_id: UUID,
        resource_id: UUID,
        token_hash: str,
        share_url: str,
        expires_at: datetime | None,
        idempotency_key: str,
    ) -> CreatedShareLink:
        fingerprint = _fingerprint(
            "CreateShareLink",
            actor_id,
            {"resourceId": resource_id, "expiresAt": expires_at},
        )
        record_key = _record_key(actor_id, "create-share-link", idempotency_key)
        replay = await self._claim_idempotency(
            actor_id, "create-share-link", idempotency_key, fingerprint
        )
        await self._authorize_resource_manager(
            actor_id, resource_id, lock=True, require_active=True
        )
        if replay is not None:
            return await self._replay_created_share(replay, record_key, fingerprint)

        share_id = uuid4()
        await self._session.execute(
            text(
                "INSERT INTO core.share_links "
                "(share_id, resource_id, token_hash, capability, status, expires_at, "
                "created_by) VALUES (:share_id, :resource_id, :token_hash, 'Read', "
                "'Active', :expires_at, :actor_id)"
            ),
            {
                "share_id": share_id,
                "resource_id": resource_id,
                "token_hash": token_hash,
                "expires_at": expires_at,
                "actor_id": actor_id,
            },
        )
        await self._record_audit(
            actor_id,
            "resource_share_link_created",
            resource_id,
            {"shareId": str(share_id), "expiresAt": _iso(expires_at)},
        )
        await self._complete_secret_idempotency(
            record_key,
            fingerprint,
            share_id,
            _encrypt_share_url(
                self._idempotency_encryption_key, record_key, fingerprint, share_url
            ),
        )
        return CreatedShareLink(
            await self._get_share_link_view(resource_id, share_id), share_url
        )

    async def list_share_links(
        self, actor_id: UUID, resource_id: UUID
    ) -> list[ShareLinkView]:
        await self._authorize_resource_manager(actor_id, resource_id)
        rows = (
            await self._session.execute(
                text(
                    "SELECT * FROM core.share_links WHERE resource_id=:resource_id "
                    "ORDER BY created_at DESC, share_id"
                ),
                {"resource_id": resource_id},
            )
        ).mappings()
        now = datetime.now(UTC)
        return [_share_link_view(row, now) for row in rows]

    async def get_share_link(
        self, actor_id: UUID, resource_id: UUID, share_id: UUID
    ) -> ShareLinkView:
        await self._authorize_resource_manager(actor_id, resource_id)
        return await self._get_share_link_view(resource_id, share_id)

    async def set_share_link_expiry(
        self,
        actor_id: UUID,
        resource_id: UUID,
        share_id: UUID,
        expires_at: datetime | None,
        idempotency_key: str,
    ) -> ShareLinkView:
        fingerprint = _fingerprint(
            "SetShareLinkExpiry",
            actor_id,
            {"resourceId": resource_id, "shareId": share_id, "expiresAt": expires_at},
        )
        record_key = _record_key(actor_id, "set-share-link-expiry", idempotency_key)
        replay = await self._claim_idempotency(
            actor_id, "set-share-link-expiry", idempotency_key, fingerprint
        )
        await self._authorize_resource_manager(actor_id, resource_id, lock=True)
        if replay is None:
            row = await self._lock_share_link(resource_id, share_id)
            if row["status"] == ShareLinkStatus.REVOKED.value:
                raise ConflictError(
                    "A revoked share link cannot be edited.", "SHARE_LINK_REVOKED"
                )
            await self._session.execute(
                text(
                    "UPDATE core.share_links SET expires_at=:expires_at "
                    "WHERE share_id=:share_id"
                ),
                {"expires_at": expires_at, "share_id": share_id},
            )
            await self._record_audit(
                actor_id,
                "resource_share_link_expiry_changed",
                resource_id,
                {"shareId": str(share_id), "expiresAt": _iso(expires_at)},
            )
            await self._complete_idempotency(record_key, fingerprint, share_id)
        return await self._get_share_link_view(resource_id, share_id)

    async def revoke_share_link(
        self,
        actor_id: UUID,
        resource_id: UUID,
        share_id: UUID,
        idempotency_key: str,
    ) -> ShareLinkView:
        fingerprint = _fingerprint(
            "RevokeShareLink",
            actor_id,
            {"resourceId": resource_id, "shareId": share_id},
        )
        record_key = _record_key(actor_id, "revoke-share-link", idempotency_key)
        replay = await self._claim_idempotency(
            actor_id, "revoke-share-link", idempotency_key, fingerprint
        )
        await self._authorize_resource_manager(actor_id, resource_id, lock=True)
        if replay is None:
            row = await self._lock_share_link(resource_id, share_id)
            if row["status"] != ShareLinkStatus.REVOKED.value:
                await self._session.execute(
                    text(
                        "UPDATE core.share_links "
                        "SET status='Revoked', revoked_at=now() "
                        "WHERE share_id=:share_id"
                    ),
                    {"share_id": share_id},
                )
                await self._record_audit(
                    actor_id,
                    "resource_share_link_revoked",
                    resource_id,
                    {"shareId": str(share_id)},
                )
            await self._complete_idempotency(record_key, fingerprint, share_id)
        return await self._get_share_link_view(resource_id, share_id)

    async def regenerate_share_link(
        self,
        actor_id: UUID,
        resource_id: UUID,
        share_id: UUID,
        token_hash: str,
        share_url: str,
        expires_at: datetime | None,
        idempotency_key: str,
    ) -> CreatedShareLink:
        fingerprint = _fingerprint(
            "RegenerateShareLink",
            actor_id,
            {"resourceId": resource_id, "shareId": share_id, "expiresAt": expires_at},
        )
        record_key = _record_key(actor_id, "regenerate-share-link", idempotency_key)
        replay = await self._claim_idempotency(
            actor_id, "regenerate-share-link", idempotency_key, fingerprint
        )
        await self._authorize_resource_manager(
            actor_id, resource_id, lock=True, require_active=True
        )
        if replay is not None:
            return await self._replay_created_share(replay, record_key, fingerprint)
        await self._lock_share_link(resource_id, share_id)
        await self._session.execute(
            text(
                "UPDATE core.share_links SET token_hash=:token_hash, "
                "capability='Read', "
                "status='Active', expires_at=:expires_at, revoked_at=NULL "
                "WHERE share_id=:share_id"
            ),
            {
                "token_hash": token_hash,
                "expires_at": expires_at,
                "share_id": share_id,
            },
        )
        await self._record_audit(
            actor_id,
            "resource_share_link_regenerated",
            resource_id,
            {"shareId": str(share_id), "expiresAt": _iso(expires_at)},
        )
        await self._complete_secret_idempotency(
            record_key,
            fingerprint,
            share_id,
            _encrypt_share_url(
                self._idempotency_encryption_key, record_key, fingerprint, share_url
            ),
        )
        return CreatedShareLink(
            await self._get_share_link_view(resource_id, share_id), share_url
        )

    async def resolve_share_token(self, token_hash: str) -> AnonymousShareGrant | None:
        row = (
            (
                await self._session.execute(
                    text(
                        "SELECT s.share_id, s.resource_id FROM core.share_links AS s "
                        "JOIN core.resources AS r ON r.resource_id=s.resource_id "
                        "JOIN core.projects AS p ON p.project_id=r.project_id "
                        "JOIN core.workspaces AS w ON w.workspace_id=p.workspace_id "
                        "WHERE s.token_hash=:token_hash AND s.capability='Read' "
                        "AND s.status='Active' "
                        "AND (s.expires_at IS NULL OR s.expires_at>:now) "
                        "AND r.lifecycle='Active' AND p.lifecycle='Active' "
                        "AND w.status='Active'"
                    ),
                    {"token_hash": token_hash, "now": datetime.now(UTC)},
                )
            )
            .mappings()
            .one_or_none()
        )
        if row is None:
            return None
        return AnonymousShareGrant(row["share_id"], row["resource_id"])

    async def _authorize_resource_manager(
        self,
        actor_id: UUID,
        resource_id: UUID,
        *,
        lock: bool = False,
        require_active: bool = False,
    ) -> tuple[UUID, UUID]:
        context = (
            await self._session.execute(
                text(
                    "SELECT p.workspace_id, p.project_id FROM core.resources AS r "
                    "JOIN core.projects AS p ON p.project_id=r.project_id "
                    "WHERE r.resource_id=:resource_id"
                ),
                {"resource_id": resource_id},
            )
        ).one_or_none()
        if context is None:
            raise NotFoundError("Resource not found.", "RESOURCE_NOT_FOUND")
        workspace_id, project_id = context
        if lock:
            workspace_status = await self._session.scalar(
                text(
                    "SELECT status FROM core.workspaces "
                    "WHERE workspace_id=:id FOR UPDATE"
                ),
                {"id": workspace_id},
            )
            project_lifecycle = await self._session.scalar(
                text(
                    "SELECT lifecycle FROM core.projects "
                    "WHERE project_id=:id FOR UPDATE"
                ),
                {"id": project_id},
            )
            resource_lifecycle = await self._session.scalar(
                text(
                    "SELECT lifecycle FROM core.resources "
                    "WHERE resource_id=:id FOR UPDATE"
                ),
                {"id": resource_id},
            )
        else:
            row = (
                await self._session.execute(
                    text(
                        "SELECT w.status, p.lifecycle, r.lifecycle "
                        "FROM core.resources AS r "
                        "JOIN core.projects AS p ON p.project_id=r.project_id "
                        "JOIN core.workspaces AS w ON w.workspace_id=p.workspace_id "
                        "WHERE r.resource_id=:resource_id"
                    ),
                    {"resource_id": resource_id},
                )
            ).one_or_none()
            if row is None:
                raise NotFoundError("Resource not found.", "RESOURCE_NOT_FOUND")
            workspace_status, project_lifecycle, resource_lifecycle = row
        if workspace_status != "Active":
            raise ConflictError("Workspace is not active.", "SHARE_SCOPE_INACTIVE")
        if require_active and (
            project_lifecycle != "Active" or resource_lifecycle != "Active"
        ):
            raise ConflictError("Resource is not active.", "SHARE_SCOPE_INACTIVE")

        owner_kind = await self._session.scalar(
            text(
                "SELECT membership_kind FROM core.workspace_members "
                "WHERE workspace_id=:workspace_id AND account_id=:actor_id"
                + (" FOR UPDATE" if lock else "")
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
        resource_role = await self._session.scalar(
            text(
                "SELECT role FROM core.resource_permissions "
                "WHERE resource_id=:resource_id AND account_id=:actor_id"
                + (" FOR UPDATE" if lock else "")
            ),
            {"resource_id": resource_id, "actor_id": actor_id},
        )
        permission = effective_permission(
            PermissionRole(project_role) if project_role is not None else None,
            PermissionRole(resource_role) if resource_role is not None else None,
            workspace_owner=owner_kind == "Owner",
        )
        if permission.role not in {PermissionRole.OWNER, PermissionRole.MANAGE}:
            raise PermissionDeniedError(
                "Resource Owner or Manage capability is required.",
                "SHARE_MANAGE_DENIED",
            )
        return workspace_id, project_id

    async def _lock_share_link(self, resource_id: UUID, share_id: UUID):
        row = (
            (
                await self._session.execute(
                    text(
                        "SELECT * FROM core.share_links WHERE share_id=:share_id "
                        "AND resource_id=:resource_id FOR UPDATE"
                    ),
                    {"share_id": share_id, "resource_id": resource_id},
                )
            )
            .mappings()
            .one_or_none()
        )
        if row is None:
            raise NotFoundError("Share link not found.", "SHARE_LINK_NOT_FOUND")
        return row

    async def _get_share_link_view(
        self, resource_id: UUID, share_id: UUID
    ) -> ShareLinkView:
        row = (
            (
                await self._session.execute(
                    text(
                        "SELECT * FROM core.share_links WHERE share_id=:share_id "
                        "AND resource_id=:resource_id"
                    ),
                    {"share_id": share_id, "resource_id": resource_id},
                )
            )
            .mappings()
            .one_or_none()
        )
        if row is None:
            raise NotFoundError("Share link not found.", "SHARE_LINK_NOT_FOUND")
        return _share_link_view(row, datetime.now(UTC))

    async def _replay_created_share(
        self, replay: dict[str, object], record_key: str, fingerprint: str
    ) -> CreatedShareLink:
        share_id = replay.get("shareId")
        encrypted_url = replay.get("encryptedShareUrl")
        if not isinstance(share_id, str) or not isinstance(encrypted_url, dict):
            raise IdempotencyConflictError(
                "The stored share response cannot be replayed."
            )
        url = _decrypt_share_url(
            self._idempotency_encryption_key,
            record_key,
            fingerprint,
            {str(key): str(value) for key, value in encrypted_url.items()},
        )
        share = await self._get_share_link_view_from_id(UUID(share_id))
        return CreatedShareLink(share, url)

    async def _get_share_link_view_from_id(self, share_id: UUID) -> ShareLinkView:
        row = (
            (
                await self._session.execute(
                    text("SELECT * FROM core.share_links WHERE share_id=:share_id"),
                    {"share_id": share_id},
                )
            )
            .mappings()
            .one_or_none()
        )
        if row is None:
            raise NotFoundError("Share link not found.", "SHARE_LINK_NOT_FOUND")
        return _share_link_view(row, datetime.now(UTC))

    async def _claim_idempotency(
        self, actor_id: UUID, operation: str, key: str, fingerprint: str
    ) -> dict[str, object] | None:
        if not key or len(key) > 200:
            raise IdempotencyConflictError("Invalid Idempotency-Key.")
        record_key = _record_key(actor_id, operation, key)
        inserted = await self._session.scalar(
            text(
                "INSERT INTO integration.idempotency_records "
                "(idempotency_key, response) VALUES (:key, :response) "
                "ON CONFLICT (idempotency_key) DO NOTHING RETURNING idempotency_key"
            ),
            {"key": record_key, "response": json.dumps({"fingerprint": fingerprint})},
        )
        if inserted is not None:
            return None
        response = await self._session.scalar(
            text(
                "SELECT response FROM integration.idempotency_records "
                "WHERE idempotency_key=:key FOR UPDATE"
            ),
            {"key": record_key},
        )
        stored = json.loads(response) if response else None
        if not isinstance(stored, dict) or stored.get("fingerprint") != fingerprint:
            raise IdempotencyConflictError(
                "Idempotency key was used for a different Share Link mutation."
            )
        return stored

    async def _complete_idempotency(
        self, record_key: str, fingerprint: str, share_id: UUID
    ) -> None:
        await self._write_idempotency(
            record_key, {"fingerprint": fingerprint, "shareId": str(share_id)}
        )

    async def _complete_secret_idempotency(
        self,
        record_key: str,
        fingerprint: str,
        share_id: UUID,
        encrypted_url: dict[str, str],
    ) -> None:
        await self._write_idempotency(
            record_key,
            {
                "fingerprint": fingerprint,
                "shareId": str(share_id),
                "encryptedShareUrl": encrypted_url,
            },
        )

    async def _write_idempotency(
        self, record_key: str, response: dict[str, object]
    ) -> None:
        retained_key = await self._session.scalar(
            text(
                "UPDATE integration.idempotency_records SET response=:response "
                "WHERE idempotency_key=:key RETURNING idempotency_key"
            ),
            {"key": record_key, "response": json.dumps(response)},
        )
        if retained_key is None:
            raise IdempotencyConflictError("Share idempotency record was not retained.")

    async def _record_audit(
        self,
        actor_id: UUID,
        action: str,
        resource_id: UUID,
        metadata: dict[str, object],
    ) -> None:
        await self._session.execute(
            text(
                "INSERT INTO audit.entries "
                "(audit_id, actor_type, actor_id, action, resource_id, metadata) "
                "VALUES (:id, 'Account', :actor_id, :action, :resource_id, "
                "CAST(:metadata AS jsonb))"
            ),
            {
                "id": uuid4(),
                "actor_id": actor_id,
                "action": action,
                "resource_id": resource_id,
                "metadata": json.dumps(metadata),
            },
        )


def _share_link_view(row, now: datetime) -> ShareLinkView:
    if row["status"] == ShareLinkStatus.REVOKED.value:
        status = ShareLinkStatus.REVOKED
    elif row["expires_at"] is not None and row["expires_at"] <= now:
        status = ShareLinkStatus.EXPIRED
    else:
        status = ShareLinkStatus.ACTIVE
    return ShareLinkView(
        share_id=row["share_id"],
        resource_id=row["resource_id"],
        capability=ShareCapability(row["capability"]),
        status=status,
        expires_at=row["expires_at"],
        created_by=row["created_by"],
        created_at=row["created_at"],
        revoked_at=row["revoked_at"],
    )


def _iso(value: datetime | None) -> str | None:
    return None if value is None else value.isoformat()
