from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable, Protocol
from uuid import UUID

from app_core.account.domain.account import Account, AccountStatus
from app_core.account.domain.password_policy import PasswordHasher
from app_core.account.ports.account_repository import AccountRepositoryPort
from app_core.account.ports.idempotency_repository import (
    IdempotencyRecord,
    IdempotencyRepositoryPort,
    IdempotencyState,
)
from app_core.common.exceptions import AuthenticationError, IdempotencyConflictError
from app_core.session.domain.session import Session, SessionStatus
from app_core.session.ports.session_repository import SessionRepositoryPort


class PasswordVerifier(Protocol):
    def verify(self, password: str, password_hash: str) -> bool: ...


_DUMMY_PASSWORD_HASH = (
    "$argon2id$v=19$m=65536,t=3,p=4$7wv+qcbPV5fHr85wVAChTQ$"
    "rK6WIg72INo6B4VZLThbfVZHNSlfmgHV24ilJEdurrw"
)


@dataclass(frozen=True)
class LoginResult:
    account: Account
    session: Session
    replaced_sessions: list[Session]
    recovery_mode: bool


class LoginWithPassword:
    def __init__(
        self,
        accounts: AccountRepositoryPort,
        sessions: SessionRepositoryPort,
        *,
        verifier: PasswordVerifier | None = None,
        now: Callable[[], datetime] | None = None,
        idempotency: IdempotencyRepositoryPort | None = None,
    ) -> None:
        self._accounts = accounts
        self._sessions = sessions
        self._verifier = verifier or PasswordHasher
        self._now = now or (lambda: datetime.now(timezone.utc))
        self._idempotency = idempotency

    async def execute(
        self,
        email: str,
        password: str,
        device_id: str,
        *,
        idempotency_key: str | None = None,
    ) -> LoginResult:
        if idempotency_key:
            prior = await self._get_or_claim(idempotency_key)
            if isinstance(prior, LoginResult):
                return prior
        record = await self._accounts.find_by_email(email.strip().casefold())
        password_hash = (
            record.password_hash if record is not None else _DUMMY_PASSWORD_HASH
        )
        password_is_valid = self._verifier.verify(password, password_hash)
        if record is None or not record.account.can_login() or not password_is_valid:
            raise _invalid_credentials()
        new_session = Session.create(
            account_id=record.account.account_id,
            device_id=device_id,
            at=self._now(),
        )
        session, replaced = await self._sessions.create_device_session_atomically(
            record.account.account_id, device_id, new_session
        )
        result = LoginResult(
            account=record.account,
            session=session,
            replaced_sessions=replaced,
            recovery_mode=record.account.is_in_recovery_mode(),
        )
        if idempotency_key and self._idempotency:
            payload = json.dumps(_login_payload(result), sort_keys=True).encode()
            await self._idempotency.complete(idempotency_key, payload)
        return result

    async def _get_or_claim(self, idempotency_key: str) -> LoginResult | None:
        if self._idempotency is None:
            raise IdempotencyConflictError("PERSISTENT_IDEMPOTENCY_REQUIRED")
        prior = await self._idempotency.get(idempotency_key)
        if isinstance(prior, IdempotencyRecord):
            if prior.state is IdempotencyState.COMPLETED and prior.response:
                return _login_from_payload(json.loads(prior.response.decode()))
        elif isinstance(prior, LoginResult):
            return prior
        claimed = await self._idempotency.claim(idempotency_key)
        if not claimed:
            for _ in range(20):
                await asyncio.sleep(0.01)
                prior = await self._idempotency.get(idempotency_key)
                if (
                    isinstance(prior, IdempotencyRecord)
                    and prior.state is IdempotencyState.COMPLETED
                    and prior.response
                ):
                    return _login_from_payload(json.loads(prior.response.decode()))
            raise IdempotencyConflictError("IDEMPOTENCY_IN_PROGRESS")
        return None


class Logout:
    def __init__(self, sessions: SessionRepositoryPort) -> None:
        self._sessions = sessions

    async def execute(self, session_id: UUID) -> None:
        await self._sessions.mark_logged_out(session_id)


class Reauthenticate:
    def __init__(
        self,
        accounts: AccountRepositoryPort,
        sessions: SessionRepositoryPort,
        *,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self._accounts = accounts
        self._sessions = sessions
        self._now = now or (lambda: datetime.now(timezone.utc))

    async def execute(self, session_id: UUID, password: str) -> Session:
        session = await self._sessions.find_by_id(session_id)
        if session is None or not session.is_active(self._now()):
            raise _invalid_credentials()
        record = await self._accounts.find_by_account_id(session.account_id)
        if (
            record is None
            or not record.account.can_login()
            or not PasswordHasher.verify(password, record.password_hash)
        ):
            raise _invalid_credentials()
        session.reauthenticate(self._now())
        await self._sessions.update_last_strong_auth(session)
        return session


def _invalid_credentials() -> AuthenticationError:
    return AuthenticationError("Invalid credentials.", "INVALID_CREDENTIALS")


def _session_payload(session: Session) -> dict[str, str]:
    return {
        "session_id": str(session.session_id),
        "device_id": session.device_id,
        "created_at": session.created_at.isoformat(),
        "expires_at": session.expires_at.isoformat(),
    }


def _session_from_payload(
    payload: dict[str, str], account_id: UUID, status: SessionStatus
) -> Session:
    created_at = datetime.fromisoformat(payload["created_at"])
    return Session(
        session_id=UUID(payload["session_id"]),
        account_id=account_id,
        device_id=payload["device_id"],
        status=status,
        created_at=created_at,
        last_seen_at=created_at,
        expires_at=datetime.fromisoformat(payload["expires_at"]),
        last_strong_auth_at=created_at,
    )


def _login_payload(result: LoginResult) -> dict[str, object]:
    account = result.account
    payload: dict[str, object] = {
        "account_id": str(account.account_id),
        "account_email": account.primary_email,
        "account_normalized_email": account.normalized_email,
        "account_status": account.status.value,
        "created_at": account.created_at.isoformat(),
        "updated_at": account.updated_at.isoformat(),
        "email_verified_at": (
            account.email_verified_at.isoformat() if account.email_verified_at else None
        ),
        "deletion_requested_at": (
            account.deletion_requested_at.isoformat()
            if account.deletion_requested_at
            else None
        ),
        "pre_deletion_status": (
            account.pre_deletion_status.value if account.pre_deletion_status else None
        ),
        "recovery_mode": result.recovery_mode,
        "session": _session_payload(result.session),
        "replaced_sessions": [
            _session_payload(session) for session in result.replaced_sessions
        ],
    }
    return payload


def _login_from_payload(payload: dict[str, object]) -> LoginResult:
    account_id = UUID(str(payload["account_id"]))
    created_at = datetime.fromisoformat(str(payload["created_at"]))
    account = Account(
        account_id=account_id,
        primary_email=str(payload["account_email"]),
        normalized_email=str(payload["account_normalized_email"]),
        status=AccountStatus(str(payload["account_status"])),
        created_at=created_at,
        updated_at=datetime.fromisoformat(str(payload["updated_at"])),
        email_verified_at=(
            datetime.fromisoformat(str(payload["email_verified_at"]))
            if payload.get("email_verified_at")
            else None
        ),
        deletion_requested_at=(
            datetime.fromisoformat(str(payload["deletion_requested_at"]))
            if payload.get("deletion_requested_at")
            else None
        ),
        pre_deletion_status=(
            AccountStatus(str(payload["pre_deletion_status"]))
            if payload.get("pre_deletion_status")
            else None
        ),
    )
    session_payload = dict(payload["session"])  # type: ignore[arg-type]
    session = _session_from_payload(session_payload, account_id, SessionStatus.ACTIVE)
    replaced = [
        _session_from_payload(dict(item), account_id, SessionStatus.REPLACED)
        for item in payload.get("replaced_sessions", [])  # type: ignore[arg-type]
    ]
    return LoginResult(
        account=account,
        session=session,
        replaced_sessions=replaced,
        recovery_mode=bool(payload["recovery_mode"]),
    )
