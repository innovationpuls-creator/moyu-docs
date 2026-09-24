"""Mailer adapters for the DOM API service (plan Task 21 §3).

``LoggingMailer`` is the Phase 7 DEVELOPMENT adapter: it "sends" mail by
writing the recipient and secret to the application log and always succeeds.
It implements both mailer protocols from app_core. A real provider adapter is
out of scope for this phase; the failure path (``MailDeliveryError``) is
exercised in tests with a failing mailer.

Security note: logging the secret is intentional and confined to this dev
adapter — the log IS the delivery channel during bootstrap (the mailer never
reaches production; see doc 16 §51 for production log hygiene).
"""

from __future__ import annotations

import logging

from app_core.account.application.password_reset import PasswordResetMailer
from app_core.account.application.registration import VerificationMailer

logger = logging.getLogger("dom.api.mailer")


class LoggingMailer(VerificationMailer, PasswordResetMailer):
    """Development adapter: delivers mail to the log, never fails."""

    async def send_verification(self, email: str, secret: str) -> None:
        logger.info("dev-mail verification to=%s secret=%s", email, secret)
        # Dev-only delivery channel for browser E2E: also append to a file the
        # harness can read (never used in production — LoggingMailer is dev).
        try:
            from pathlib import Path

            target = Path(__file__).resolve().parent.parent.parent / "dev-mail.log"
            with target.open("a", encoding="utf-8") as fh:
                fh.write(f"to={email} secret={secret}\n")
        except OSError:
            logger.warning("dev-mail file delivery unavailable", exc_info=True)

    async def send_password_reset(self, email: str, secret: str) -> None:
        logger.info("dev-mail password-reset to=%s secret=%s", email, secret)
