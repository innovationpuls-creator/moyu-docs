from __future__ import annotations

from collections.abc import Callable
from datetime import datetime

from app_core.account.application.registration import MailDeliveryError
from app_core.account.domain.password_policy import PasswordHasher, PasswordPolicy
from app_core.account.domain.token import OneTimeToken, OneTimeTokenType
from app_core.common.exceptions import AuthenticationError

_PUBLIC_MESSAGE = "If this email is registered, a reset email has been sent."


class PasswordResetMailer:
    async def send_password_reset(self, email: str, secret: str) -> None: ...


class RequestPasswordReset:
    def __init__(
        self, accounts, tokens, audit, mailer, *, now: Callable[[], datetime]
    ) -> None:
        self._accounts, self._tokens, self._audit, self._mailer, self._now = (
            accounts,
            tokens,
            audit,
            mailer,
            now,
        )

    async def execute(self, email: str):
        record = await self._accounts.find_by_email(email)
        if record is None:
            return type("Result", (), {"public_message": _PUBLIC_MESSAGE})()
        now = self._now()
        await self._tokens.invalidate_pending(
            record.account.account_id, OneTimeTokenType.PASSWORD_RESET, now
        )
        token, secret = OneTimeToken.issue(
            account_id=record.account.account_id,
            token_type=OneTimeTokenType.PASSWORD_RESET,
            at=now,
        )
        await self._tokens.save(token)
        try:
            await self._mailer.send_password_reset(record.account.primary_email, secret)
        except MailDeliveryError:
            await self._audit.append(
                actor_type="Account",
                actor_id=record.account.account_id,
                action="PasswordResetDeliveryFailed",
                metadata={"delivery": "failed"},
            )
        return type("Result", (), {"public_message": _PUBLIC_MESSAGE})()


class ResetPassword:
    def __init__(
        self, accounts, tokens, sessions, audit, *, now: Callable[[], datetime]
    ) -> None:
        self._accounts, self._tokens, self._sessions, self._audit, self._now = (
            accounts,
            tokens,
            sessions,
            audit,
            now,
        )

    async def execute(self, secret: str, password: str) -> None:
        PasswordPolicy.validate(password)
        token = await self._tokens.consume_password_reset_by_secret(secret, self._now())
        if token is None:
            raise AuthenticationError(
                "PASSWORD_RESET_TOKEN_INVALID", "PASSWORD_RESET_TOKEN_INVALID"
            )
        await self._accounts.update_password_hash(
            token.account_id, PasswordHasher.hash(password)
        )
        await self._sessions.revoke_all_sessions(token.account_id, "PasswordReset")
        await self._audit.append(
            actor_type="Account", actor_id=token.account_id, action="PasswordReset"
        )
