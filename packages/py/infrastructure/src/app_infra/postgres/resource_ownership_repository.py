"""Permission-owned read/grant adapter for collab.resource_ownership."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID

from app_core.resource.ports import ReadOnlyResourceOwnershipPort
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


@dataclass(frozen=True)
class ResourceOwnership:
    resource_id: UUID
    owner_account_id: UUID
    epoch: int
    lease_until: datetime | None


class PostgresResourceOwnershipRepository(ReadOnlyResourceOwnershipPort):
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def grant(
        self, resource_id: UUID, owner_account_id: UUID, *, lease_seconds: int = 3600
    ) -> ResourceOwnership:
        row = (
            (
                await self._session.execute(
                    text(
                        "INSERT INTO collab.resource_ownership "
                        "(resource_id,owner_account_id,epoch,lease_until) "
                        "VALUES (:rid,:acc,1,:lease) ON CONFLICT (resource_id) "
                        "DO UPDATE SET owner_account_id=EXCLUDED.owner_account_id,"
                        "epoch=resource_ownership.epoch+1,lease_until=EXCLUDED.lease_until,"
                        "updated_at=now() RETURNING *"
                    ),
                    {
                        "rid": resource_id,
                        "acc": owner_account_id,
                        "lease": datetime.now(UTC) + timedelta(seconds=lease_seconds),
                    },
                )
            )
            .mappings()
            .one()
        )
        return _to_ownership(row)

    async def authorize(self, actor_id: UUID, scope_id: UUID, operation: str) -> bool:
        if operation == "resource.create":
            # Project-scoped create: the Project's workspace Owner may create.
            row = (
                (
                    await self._session.execute(
                        text(
                            "SELECT 1 FROM core.workspace_members wm "
                            "JOIN core.projects p ON p.workspace_id=wm.workspace_id "
                            "WHERE p.project_id=:pid AND wm.account_id=:acc "
                            "AND wm.membership_kind='Owner' LIMIT 1"
                        ),
                        {"pid": scope_id, "acc": actor_id},
                    )
                )
                .mappings()
                .one_or_none()
            )
            return row is not None
        row = (
            (
                await self._session.execute(
                    text(
                        "SELECT 1 FROM collab.resource_ownership "
                        "WHERE resource_id=:rid AND owner_account_id=:acc LIMIT 1"
                    ),
                    {"rid": scope_id, "acc": actor_id},
                )
            )
            .mappings()
            .one_or_none()
        )
        return row is not None


def _to_ownership(mapping) -> ResourceOwnership:
    return ResourceOwnership(
        resource_id=mapping["resource_id"],
        owner_account_id=mapping["owner_account_id"],
        epoch=mapping["epoch"],
        lease_until=mapping["lease_until"],
    )
