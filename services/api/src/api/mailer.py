"""Mailer adapters for the DOM API service (plan Task 21 §3, doc 16 §51).

``LoggingMailer`` is the DEVELOPMENT adapter: it "sends" mail by writing the
recipient and secret to the application log and always succeeds. It implements
both mailer protocols from app_core.

``SmtpMailer`` is the PRODUCTION adapter: real delivery over SMTP (stdlib
``smtplib`` bridged through ``asyncio.to_thread`` — zero new runtime
dependency). Selected via ``MAILER_PROVIDER=smtp``; wiring validates required
configuration and fails fast at startup (missing SMTP_HOST/SMTP_FROM).

Security note: ``LoggingMailer`` logs the secret intentionally and is confined
to the dev adapter — it must never reach production (doc 16 §51 production log
hygiene). ``SmtpMailer`` never logs the secret; only recipient + subject +
failure class are observable.
"""

from __future__ import annotations

import asyncio
import logging
import smtplib
from email.message import EmailMessage
from pathlib import Path

from app_core.account.application.password_reset import PasswordResetMailer
from app_core.account.application.registration import (
    MailDeliveryError,
    VerificationMailer,
)

logger = logging.getLogger("dom.api.mailer")

SUBJECT_VERIFY = "墨屿 · 验证您的邮箱"
SUBJECT_RESET = "墨屿 · 重置您的密码"

# Dev delivery channel (LoggingMailer only): recipient + secret on disk so
# browser E2E and local bootstrap can drive the real verification flow.
_DEV_MAIL_LOG = Path(__file__).resolve().parent.parent.parent / "dev-mail.log"


class LoggingMailer(VerificationMailer, PasswordResetMailer):
    """Development adapter: delivers mail to the log, never fails."""

    async def send_verification(self, email: str, secret: str) -> None:
        logger.info("dev-mail verification to=%s secret=%s", email, secret)
        _append_dev_mail(f"to={email} secret={secret}")

    async def send_password_reset(self, email: str, secret: str) -> None:
        logger.info("dev-mail password-reset to=%s secret=%s", email, secret)
        _append_dev_mail(f"to={email} secret={secret}")


def _append_dev_mail(line: str) -> None:
    try:
        with _DEV_MAIL_LOG.open("a", encoding="utf-8") as fh:
            fh.write(f"{line}\n")
    except OSError:
        logger.warning("dev-mail file delivery unavailable", exc_info=True)


class SmtpMailer(VerificationMailer, PasswordResetMailer):
    """Production adapter: real SMTP delivery (stdlib smtplib, zero new deps).

    The async protocol is bridged with ``asyncio.to_thread``; delivery failures
    (any SMTP-level error) surface as ``MailDeliveryError`` so the registration
    / reset use-cases keep their uniform "mail delivery failed" handling.
    """

    def __init__(
        self,
        *,
        host: str,
        port: int,
        from_addr: str,
        link_base_url: str,
        username: str | None = None,
        password: str | None = None,
        starttls: bool = True,
        timeout: float = 10.0,
    ) -> None:
        self._host = host
        self._port = port
        self._from = from_addr
        self._username = username
        self._password = password
        self._starttls = starttls
        self._timeout = timeout
        self._link_base = link_base_url.rstrip("/")

    async def send_verification(self, email: str, secret: str) -> None:
        link = f"{self._link_base}/verify-email?token={secret}"
        body = (
            "你好，\n\n"
            "欢迎使用墨屿 · Moyu Docs。请打开下面的链接完成邮箱验证"
            "（24 小时内有效，单次使用）：\n\n"
            f"{link}\n\n"
            "如果这不是你的操作，请忽略此邮件。"
        )
        await self._deliver(email, SUBJECT_VERIFY, body)

    async def send_password_reset(self, email: str, secret: str) -> None:
        link = f"{self._link_base}/reset-password?token={secret}"
        body = (
            "你好，\n\n"
            "我们收到了重置墨屿账号密码的请求。请在 15 分钟内打开下面的链接"
            "设置新密码（单次使用）：\n\n"
            f"{link}\n\n"
            "如果这不是你的操作，请忽略此邮件，并留意账号安全。"
        )
        await self._deliver(email, SUBJECT_RESET, body)

    async def _deliver(self, to_addr: str, subject: str, body: str) -> None:
        try:
            await asyncio.to_thread(self._deliver_sync, to_addr, subject, body)
        except Exception as exc:
            # Never log the secret — recipient + failure class only (doc 16 §51).
            logger.warning(
                "smtp delivery failed to=%s: %s",
                to_addr,
                type(exc).__name__,
            )
            raise MailDeliveryError(f"smtp delivery failed: {exc}") from exc
        logger.info("smtp delivered to=%s subject=%s", to_addr, subject)

    def _deliver_sync(self, to_addr: str, subject: str, body: str) -> None:
        message = EmailMessage()
        message["From"] = self._from
        message["To"] = to_addr
        message["Subject"] = subject
        message.set_content(body)
        with smtplib.SMTP(self._host, self._port, timeout=self._timeout) as smtp:
            smtp.ehlo()
            if self._starttls:
                smtp.starttls()
                smtp.ehlo()
            if self._username:
                smtp.login(self._username, self._password or "")
            smtp.send_message(message)
