from __future__ import annotations

import hashlib
from collections.abc import Mapping
from datetime import datetime
from typing import Any
from uuid import UUID

from app_core.account.domain.token import OneTimeToken, OneTimeTokenType
from app_core.account.ports.token_repository import TokenRepositoryPort
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


class PostgresTokenRepository(TokenRepositoryPort):
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def save(self, token: OneTimeToken) -> None:
        await self._session.execute(
            text(
                """
                INSERT INTO auth.one_time_tokens
                    (token_id, account_id, token_type, token_hash, expires_at,
                     consumed_at, created_at)
                VALUES (:token_id, :account_id, :token_type, :token_hash,
                        :expires_at, :consumed_at, :created_at)
                """
            ),
            {
                "token_id": token.token_id,
                "account_id": token.account_id,
                "token_type": token.token_type.value,
                "token_hash": token.token_hash,
                "expires_at": token.expires_at,
                "consumed_at": token.consumed_at,
                "created_at": token.created_at,
            },
        )

    async def invalidate_pending(
        self, account_id: UUID, token_type: OneTimeTokenType, at: datetime
    ) -> int:
        result = await self._session.execute(
            text(
                """
                UPDATE auth.one_time_tokens
                SET consumed_at = :at
                WHERE account_id = :account_id
                  AND token_type = :token_type
                  AND consumed_at IS NULL
                """
            ),
            {"account_id": account_id, "token_type": token_type.value, "at": at},
        )
        return result.rowcount if hasattr(result, "rowcount") else 0

    async def find_by_hash(self, token_hash: str) -> OneTimeToken | None:
        result = await self._session.execute(
            text(
                """
                SELECT token_id, account_id, token_type, token_hash,
                       created_at, expires_at, consumed_at
                FROM auth.one_time_tokens
                WHERE token_hash = :token_hash AND consumed_at IS NULL
                ORDER BY created_at DESC
                LIMIT 1
                """
            ),
            {"token_hash": token_hash},
        )
        row = result.mappings().first()
        return _to_entity(row) if row else None

    async def count_recent(
        self, account_id: UUID, token_type: OneTimeTokenType, since: datetime
    ) -> int:
        result = await self._session.execute(
            text(
                "SELECT COUNT(*) FROM auth.one_time_tokens "
                "WHERE account_id = :account_id AND token_type = :token_type "
                "AND created_at >= :since"
            ),
            {"account_id": account_id, "token_type": token_type.value, "since": since},
        )
        return result.scalar_one()

    async def consume_by_secret_for_account(
        self, secret: str, account_id: UUID, at: datetime
    ) -> OneTimeToken | None:
        token_hash = _hash_token(secret)
        result = await self._session.execute(
            text(
                "UPDATE auth.one_time_tokens SET consumed_at = :at "
                "WHERE token_hash = :token_hash AND account_id = :account_id "
                "AND token_type = :token_type "
                "AND consumed_at IS NULL AND expires_at > :at "
                "RETURNING token_id, account_id, token_type, token_hash, "
                "created_at, expires_at, consumed_at"
            ),
            {
                "token_hash": token_hash,
                "account_id": account_id,
                "token_type": OneTimeTokenType.EMAIL_VERIFICATION.value,
                "at": at,
            },
        )
        row = result.mappings().first()
        return _to_entity(row) if row else None

    async def consume_password_reset_by_secret(
        self, secret: str, at: datetime
    ) -> OneTimeToken | None:
        token_hash = _hash_token(secret)
        result = await self._session.execute(
            text(
                "UPDATE auth.one_time_tokens SET consumed_at = :at "
                "WHERE token_hash = :token_hash AND token_type = :token_type "
                "AND consumed_at IS NULL AND expires_at > :at "
                "RETURNING token_id, account_id, token_type, token_hash, "
                "created_at, expires_at, consumed_at"
            ),
            {
                "token_hash": token_hash,
                "token_type": OneTimeTokenType.PASSWORD_RESET.value,
                "at": at,
            },
        )
        row = result.mappings().first()
        return _to_entity(row) if row else None

    async def consume_by_secret(self, secret: str, at: datetime) -> OneTimeToken | None:
        token_hash = _hash_token(secret)
        result = await self._session.execute(
            text(
                """
                UPDATE auth.one_time_tokens
                SET consumed_at = :at
                WHERE token_hash = :token_hash
                  AND consumed_at IS NULL
                  AND expires_at > :at
                RETURNING token_id, account_id, token_type, token_hash,
                          created_at, expires_at, consumed_at
                """
            ),
            {"token_hash": token_hash, "at": at},
        )
        row = result.mappings().first()
        return _to_entity(row) if row else None


def _hash_token(secret: str) -> str:
    return hashlib.sha256(secret.encode("utf-8")).hexdigest()


def _to_entity(row: Mapping[Any, Any]) -> OneTimeToken:
    values = row
    return OneTimeToken(
        token_id=values["token_id"],
        account_id=values["account_id"],
        token_type=OneTimeTokenType(values["token_type"]),
        token_hash=values["token_hash"],
        created_at=values["created_at"],
        expires_at=values["expires_at"],
        consumed_at=values["consumed_at"],
    )
