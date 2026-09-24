from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from app_core.workspace.ports.purge import (
    PurgeCandidate,
    PurgeResult,
    WorkspaceMembershipCleanupPort,
    WorkspacePurgeRepository,
    purge_effect_key,
)


@dataclass(frozen=True)
class PurgePayload:
    workspace_id: UUID
    purge_eligible_at: datetime
    schema_version: str = "1.0.0"
    handler_version: str = "1.0.0"

    def as_dict(self) -> dict[str, str]:
        return {
            "workspaceId": str(self.workspace_id),
            "purgeEligibleAt": self.purge_eligible_at.isoformat(),
            "schemaVersion": self.schema_version,
            "handlerVersion": self.handler_version,
        }


class PurgePolicy:
    @staticmethod
    def eligible(
        *, status: str, purge_eligible_at: datetime | None, now: datetime
    ) -> bool:
        return (
            status == "DeletionPending"
            and purge_eligible_at is not None
            and purge_eligible_at <= now
        )

    @staticmethod
    def payload(candidate: PurgeCandidate) -> PurgePayload:
        return PurgePayload(candidate.workspace_id, candidate.purge_eligible_at)

    @staticmethod
    def effect_key(workspace_id: UUID) -> str:
        return purge_effect_key(workspace_id)


class RetryablePurgeError(RuntimeError):
    pass


class FatalPurgeError(RuntimeError):
    pass


class PurgeWorkspace:
    def __init__(
        self,
        repository: WorkspacePurgeRepository,
        memberships: WorkspaceMembershipCleanupPort,
    ) -> None:
        self._repository = repository
        self._memberships = memberships

    async def execute(self, workspace_id: UUID) -> PurgeResult:
        candidate = await self._repository.get_for_purge(workspace_id)
        if candidate is None:
            return PurgeResult(workspace_id, "Missing")  # type: ignore[arg-type]
        try:
            result = await self._repository.purge_workspace(workspace_id)
            await self._memberships.remove_workspace_memberships(workspace_id)
            return result
        except (TimeoutError, ConnectionError) as exc:
            raise RetryablePurgeError(str(exc)) from exc
        except Exception as exc:
            raise FatalPurgeError(str(exc)) from exc
