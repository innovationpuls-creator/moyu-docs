from __future__ import annotations

from app_core.permission.application.administration import PermissionAdministration
from app_infra.postgres.permission_administration_repository import (
    PostgresPermissionAdministrationRepository,
    decode_invitation_idempotency_encryption_key,
)
from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from api.config import settings
from api.dependencies.auth import get_db_session


def get_permission_administration(
    session: AsyncSession = Depends(get_db_session),
) -> PermissionAdministration:
    encryption_key = decode_invitation_idempotency_encryption_key(
        settings.invitation_idempotency_encryption_key
    )
    repository = PostgresPermissionAdministrationRepository(session, encryption_key)
    return PermissionAdministration(repository)
