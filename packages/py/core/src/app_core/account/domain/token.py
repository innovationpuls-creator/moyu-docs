from __future__ import annotations

import hashlib
import hmac
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum
from uuid import UUID, uuid4


class OneTimeTokenType(StrEnum):
    EMAIL_VERIFICATION = "EmailVerification"
    PASSWORD_RESET = "PasswordReset"


@dataclass
class OneTimeToken:
    token_id: UUID
    account_id: UUID
    token_type: OneTimeTokenType
    token_hash: str
    created_at: datetime
    expires_at: datetime
    consumed_at: datetime | None = None

    @classmethod
    def issue(
        cls, *, account_id: UUID, token_type: OneTimeTokenType, at: datetime
    ) -> tuple[OneTimeToken, str]:
        secret = secrets.token_urlsafe(32)
        return (
            cls(
                token_id=uuid4(),
                account_id=account_id,
                token_type=token_type,
                token_hash=_hash_token(secret),
                created_at=at,
                expires_at=at + _lifetime_for(token_type),
            ),
            secret,
        )

    def matches(self, secret: str, at: datetime) -> bool:
        return (
            self.consumed_at is None
            and at < self.expires_at
            and hmac.compare_digest(self.token_hash, _hash_token(secret))
        )

    def consume(self, secret: str, at: datetime) -> bool:
        if not self.matches(secret, at):
            return False
        self.consumed_at = at
        return True


def _hash_token(secret: str) -> str:
    return hashlib.sha256(secret.encode("utf-8")).hexdigest()


def _lifetime_for(token_type: OneTimeTokenType) -> timedelta:
    if token_type is OneTimeTokenType.EMAIL_VERIFICATION:
        return timedelta(hours=24)
    return timedelta(minutes=15)
