from __future__ import annotations

from app_core.permission.application.share_links import ShareLinkAdministration
from app_infra.postgres.share_link_repository import (
    PostgresShareLinkRepository,
    decode_share_link_idempotency_encryption_key,
)
from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from api.config import settings
from api.dependencies.auth import get_db_session


def get_share_link_administration(
    session: AsyncSession = Depends(get_db_session),
) -> ShareLinkAdministration:
    encryption_key = decode_share_link_idempotency_encryption_key(
        settings.share_link_idempotency_encryption_key
    )
    repository = PostgresShareLinkRepository(session, encryption_key)
    return ShareLinkAdministration(repository)
