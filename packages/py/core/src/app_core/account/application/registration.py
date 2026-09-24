from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Protocol
from uuid import UUID

from app_core.account.domain.account import Account, AccountStatus
from app_core.account.domain.password_policy import PasswordHasher, PasswordPolicy
from app_core.account.domain.timing_shield import UNIFORM_AUTH_MESSAGES, TimingShield
from app_core.account.domain.token import OneTimeToken, OneTimeTokenType
from app_core.account.ports.idempotency_repository import (
    IdempotencyRecord,
    IdempotencyState,
)
from app_core.common.exceptions import (
    AuthenticationError,
    DuplicateEmailError,
    IdempotencyConflictError,
    RateLimitError,
    ValidationError,
)
from app_core.session.domain.session import Session, SessionStatus


class MailDeliveryError(Exception):
    pass


class VerificationMailer(Protocol):
    async def send_verification(self, email: str, secret: str) -> None: ...


@dataclass(frozen=True)
class RegistrationResult:
    accepted: bool
    account: Account
    session: Session | None
    verification_secret: str | None
    mail_delivery_failed: bool
    public_message: str


class RegisterAccount:
    def __init__(
        self,
        accounts,
        sessions,
        tokens,
        audit,
        mailer,
        *,
        now=lambda: datetime.now(timezone.utc),
        idempotency=None,
        shield: TimingShield | None = None,
        require_verification: bool = True,
    ):
        self._accounts, self._sessions, self._tokens = accounts, sessions, tokens
        self._audit, self._mailer, self._now = audit, mailer, now
        self._idempotency = idempotency
        self._shield = shield or TimingShield()
        # 邮箱验证开关（产品决策 2026-09：停用验证 = 注册即 Active）。保留
        # True 分支与 VerifyEmail/ResendVerificationEmail 端点作为兼容层。
        self._require_verification = require_verification

    async def execute(  # noqa: C901
        self,
        email: str,
        password: str,
        device_id: str,
        *,
        idempotency_key: str | None = None,
    ) -> RegistrationResult:
        if idempotency_key:
            if self._idempotency is None:
                raise IdempotencyConflictError("PERSISTENT_IDEMPOTENCY_REQUIRED")
            prior = await self._idempotency.get(idempotency_key)
            if isinstance(prior, IdempotencyRecord):
                if prior.state is IdempotencyState.COMPLETED and prior.response:
                    return _result_from_payload(json.loads(prior.response.decode()))
            elif isinstance(prior, RegistrationResult):
                return prior
            if not hasattr(self._idempotency, "claim"):
                raise IdempotencyConflictError("PERSISTENT_IDEMPOTENCY_REQUIRED")
            if not await self._idempotency.claim(idempotency_key):
                for _ in range(20):
                    await asyncio.sleep(0.01)
                    prior = await self._idempotency.get(idempotency_key)
                    if (
                        isinstance(prior, IdempotencyRecord)
                        and prior.state is IdempotencyState.COMPLETED
                        and prior.response
                    ):
                        return _result_from_payload(json.loads(prior.response.decode()))
                raise IdempotencyConflictError("IDEMPOTENCY_IN_PROGRESS")
        PasswordPolicy.validate(password)
        existing = await self._accounts.find_by_email(email)
        if existing is not None:
            result = await self._existing_result(existing.account)
            if idempotency_key and self._idempotency:
                await _store_result(self._idempotency, idempotency_key, result)
            return result
        now = self._now()
        account = Account.create_with_email(email, at=now)
        try:
            await self._accounts.save(account, PasswordHasher.hash(password))
        except DuplicateEmailError:
            result = await self._existing_result(account)
            if idempotency_key and self._idempotency:
                await _store_result(self._idempotency, idempotency_key, result)
            return result
        session = Session.create(
            account_id=account.account_id, device_id=device_id, at=now
        )
        session, _ = await self._sessions.create_device_session_atomically(
            account.account_id, device_id, session
        )
        await self._audit.append(
            actor_type="Account", actor_id=account.account_id, action="AccountCreated"
        )
        if not self._require_verification:
            # 停用邮箱验证：注册即 Active，不签发验证 token、不发送验证邮件。
            account.verify_email(at=now)
            await self._accounts.update(account)
            await self._audit.append(
                actor_type="Account",
                actor_id=account.account_id,
                action="RegistrationActivated",
            )
            result = RegistrationResult(
                True, account, session, None, False, _REGISTER_SUCCESS_MESSAGE
            )
        else:
            token, secret = OneTimeToken.issue(
                account_id=account.account_id,
                token_type=OneTimeTokenType.EMAIL_VERIFICATION,
                at=now,
            )
            await self._tokens.save(token)
            failed = False
            try:
                await self._mailer.send_verification(account.primary_email, secret)
            except MailDeliveryError:
                failed = True
                await self._audit.append(
                    actor_type="Account",
                    actor_id=account.account_id,
                    action="VerificationEmailDeliveryFailed",
                    metadata={"delivery": "failed"},
                )
            result = RegistrationResult(
                True, account, session, secret, failed, _REGISTER_SUCCESS_MESSAGE
            )
        if idempotency_key and self._idempotency:
            await _store_result(self._idempotency, idempotency_key, result)
        return result

    async def _existing_result(self, account: Account) -> RegistrationResult:
        # A new registration hashes the password before saving; equalize the
        # duration of the existing-email path with constant Argon2id work so
        # the endpoint does not reveal whether the email is registered
        # (FR-AUTH-007).
        self._shield.perform_dummy_hash()
        return RegistrationResult(
            True, account, None, None, False, _REGISTER_SUCCESS_MESSAGE
        )


class VerifyEmail:
    def __init__(self, accounts, tokens, audit, *, now):
        self._accounts, self._tokens, self._audit, self._now = (
            accounts,
            tokens,
            audit,
            now,
        )

    async def execute(self, secret: str, account_id: UUID) -> Account:
        now = self._now()
        record = await self._accounts.find_by_account_id(account_id)
        if record is None or record.account.status in {
            AccountStatus.DISABLED,
            AccountStatus.DELETION_PENDING,
            AccountStatus.DELETED,
        }:
            raise AuthenticationError(
                "EMAIL_VERIFICATION_TOKEN_INVALID",
                "EMAIL_VERIFICATION_TOKEN_INVALID",
            )
        token = await self._tokens.consume_by_secret_for_account(
            secret, account_id, now
        )
        if token is None or token.account_id != account_id:
            raise AuthenticationError(
                "EMAIL_VERIFICATION_TOKEN_INVALID",
                "EMAIL_VERIFICATION_TOKEN_INVALID",
            )
        record.account.verify_email(at=now)
        await self._accounts.update(record.account)
        await self._tokens.invalidate_pending(
            account_id, OneTimeTokenType.EMAIL_VERIFICATION, now
        )
        await self._audit.append(
            actor_type="Account", actor_id=account_id, action="EmailVerified"
        )
        return record.account


class ResendVerificationEmail:
    def __init__(self, accounts, tokens, mailer, *, now, audit=None):
        self._accounts, self._tokens, self._mailer, self._now, self._audit = (
            accounts,
            tokens,
            mailer,
            now,
            audit,
        )

    async def execute(self, account_id: UUID) -> str:
        record = await self._accounts.find_by_account_id(account_id)
        if (
            record is None
            or record.account.status is not AccountStatus.PENDING_VERIFICATION
        ):
            raise ValidationError("INVALID_REQUEST", "INVALID_REQUEST")
        now = self._now()
        if (
            await self._tokens.count_recent(
                account_id,
                OneTimeTokenType.EMAIL_VERIFICATION,
                now - timedelta(seconds=60),
            )
            or await self._tokens.count_recent(
                account_id, OneTimeTokenType.EMAIL_VERIFICATION, now - timedelta(days=1)
            )
            >= 5
        ):
            raise RateLimitError("RATE_LIMITED", "RATE_LIMITED")
        token, secret = OneTimeToken.issue(
            account_id=account_id,
            token_type=OneTimeTokenType.EMAIL_VERIFICATION,
            at=now,
        )
        try:
            await self._mailer.send_verification(record.account.primary_email, secret)
        except MailDeliveryError:
            if self._audit:
                await self._audit.append(
                    actor_type="Account",
                    actor_id=account_id,
                    action="VerificationEmailDeliveryFailed",
                )
            raise
        await self._tokens.save(token)
        return secret


async def _store_result(store: object, key: str, result: RegistrationResult) -> None:
    payload = json.dumps(_result_payload(result), sort_keys=True).encode()
    if hasattr(store, "complete"):
        await store.complete(key, payload)
    else:
        raise IdempotencyConflictError("PERSISTENT_IDEMPOTENCY_REQUIRED")


def _result_payload(result: RegistrationResult) -> dict[str, object]:
    payload: dict[str, object] = {
        "accepted": result.accepted,
        "account_id": str(result.account.account_id),
        "account_email": result.account.primary_email,
        "account_normalized_email": result.account.normalized_email,
        "account_status": result.account.status.value,
        "created_at": result.account.created_at.isoformat(),
        "mail_delivery_failed": result.mail_delivery_failed,
        "public_message": result.public_message,
        "verification_secret": None,
    }
    if result.session is not None:
        payload["session_id"] = str(result.session.session_id)
        payload["device_id"] = result.session.device_id
        payload["expires_at"] = result.session.expires_at.isoformat()
    return payload


def _result_from_payload(payload: dict[str, object]) -> RegistrationResult:
    account_id = UUID(str(payload["account_id"]))
    created_at = datetime.fromisoformat(str(payload["created_at"]))
    account = Account(
        account_id=account_id,
        primary_email=str(payload["account_email"]),
        normalized_email=str(payload["account_normalized_email"]),
        status=AccountStatus(str(payload["account_status"])),
        created_at=created_at,
        updated_at=created_at,
    )
    session = None
    if payload.get("session_id") is not None:
        session = Session(
            session_id=UUID(str(payload["session_id"])),
            account_id=account_id,
            device_id=str(payload["device_id"]),
            status=SessionStatus.ACTIVE,
            created_at=created_at,
            last_seen_at=created_at,
            expires_at=datetime.fromisoformat(str(payload["expires_at"])),
            last_strong_auth_at=created_at,
        )
    return RegistrationResult(
        accepted=bool(payload["accepted"]),
        account=account,
        session=session,
        verification_secret=None,
        mail_delivery_failed=bool(payload["mail_delivery_failed"]),
        public_message=str(payload["public_message"]),
    )


_REGISTER_SUCCESS_MESSAGE = UNIFORM_AUTH_MESSAGES["REGISTER_SUCCESS_EN"]
