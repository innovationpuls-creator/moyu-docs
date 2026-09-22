from __future__ import annotations

from uuid import UUID

from app_core.common.exceptions import RateLimitError
from redis.asyncio import Redis

LOGIN_MAX_FAILURES = 5
LOGIN_LOCKOUT_SECONDS = 15 * 60  # temporary cooldown, never a permanent lock
RESEND_COOLDOWN_SECONDS = 60
RESEND_MAX_PER_24H = 5
RESEND_WINDOW_SECONDS = 24 * 60 * 60


def login_rate_key(identifier: str) -> str:
    return f"ratelimit:login:{identifier}"


def verify_email_last_sent_key(account_id: UUID) -> str:
    return f"ratelimit:verify_email:{account_id}:last_sent"


def verify_email_count_key(account_id: UUID) -> str:
    return f"ratelimit:verify_email:{account_id}:count"


class RateLimiter:
    """Progressive auth rate limiter backed by Valkey.

    Login failures are counted per ``identifier`` (IP / account / device
    context composed by the API layer); reaching ``LOGIN_MAX_FAILURES`` enters
    a temporary 15-minute cooldown instead of a permanent lock
    (FR-AUTH-035: AC-035.1/AC-035.3, docs/architecture/16 §54-56, §114).
    Verification-email resends are gated by a 60s cooldown plus a 5-per-24h
    quota (FR-AUTH-004 AC-004.1).
    """

    def __init__(
        self,
        client: Redis,
        *,
        login_lockout_seconds: int = LOGIN_LOCKOUT_SECONDS,
        resend_cooldown_seconds: int = RESEND_COOLDOWN_SECONDS,
        resend_max_per_window: int = RESEND_MAX_PER_24H,
        resend_window_seconds: int = RESEND_WINDOW_SECONDS,
    ) -> None:
        self._client = client
        self._login_lockout_seconds = login_lockout_seconds
        self._resend_cooldown_seconds = resend_cooldown_seconds
        self._resend_max_per_window = resend_max_per_window
        self._resend_window_seconds = resend_window_seconds

    async def check_login_rate(self, identifier: str) -> None:
        failures = int(await self._client.get(login_rate_key(identifier)) or "0")
        if failures >= LOGIN_MAX_FAILURES:
            raise RateLimitError(
                "登录失败次数过多，已进入 15 分钟临时锁定，请稍后再试",
                error_code="RATE_LIMITED",
            )

    async def record_login_failure(self, identifier: str) -> None:
        key = login_rate_key(identifier)
        pipeline = self._client.pipeline()
        pipeline.incr(key)
        # Rolling window: the cooldown counts from the last failure, so the
        # lock is always temporary and self-heals within 15 minutes.
        pipeline.expire(key, self._login_lockout_seconds)
        await pipeline.execute()

    async def clear_login_failure(self, identifier: str) -> None:
        await self._client.delete(login_rate_key(identifier))

    async def check_resend_verification_quota(self, account_id: UUID) -> None:
        if await self._client.exists(verify_email_last_sent_key(account_id)):
            raise RateLimitError(
                "验证邮件重发过于频繁，请 60 秒后再试",
                error_code="RATE_LIMITED",
            )
        count = int(await self._client.get(verify_email_count_key(account_id)) or "0")
        if count >= self._resend_max_per_window:
            raise RateLimitError(
                "验证邮件 24 小时内最多发送 5 次，请稍后再试",
                error_code="RATE_LIMITED",
            )

    async def record_resend_verification(self, account_id: UUID) -> None:
        """Record a verification-email send (call after the mail is queued)."""
        pipeline = self._client.pipeline()
        if self._resend_cooldown_seconds > 0:
            pipeline.set(
                verify_email_last_sent_key(account_id),
                "1",
                ex=self._resend_cooldown_seconds,
            )
        pipeline.incr(verify_email_count_key(account_id))
        pipeline.expire(verify_email_count_key(account_id), self._resend_window_seconds)
        await pipeline.execute()
