from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from uuid import UUID

from app_core.permission.domain.access_control import PermissionCapability


class ShareCapability(StrEnum):
    READ = "Read"


class ShareLinkStatus(StrEnum):
    ACTIVE = "Active"
    REVOKED = "Revoked"
    EXPIRED = "Expired"


@dataclass(frozen=True)
class ShareLinkView:
    share_id: UUID
    resource_id: UUID
    capability: ShareCapability
    status: ShareLinkStatus
    expires_at: datetime | None
    created_by: UUID
    created_at: datetime
    revoked_at: datetime | None


@dataclass(frozen=True)
class CreatedShareLink:
    share_link: ShareLinkView
    share_url: str = field(repr=False)


@dataclass(frozen=True)
class AnonymousShareGrant:
    share_id: UUID
    resource_id: UUID
    capability: ShareCapability = ShareCapability.READ

    def allows(self, capability: PermissionCapability) -> bool:
        return capability is PermissionCapability.READ

    @property
    def can_participate_in_presence(self) -> bool:
        return False
