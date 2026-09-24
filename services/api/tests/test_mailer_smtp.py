"""SmtpMailer + build_mailer wiring gate tests (doc 16 §51).

Covers: real SMTP payload construction (verification / reset links), optional
auth, failure -> MailDeliveryError (uniform use-case handling), and the
fail-fast provider configuration gate.
"""

from __future__ import annotations

import smtplib
from email.message import EmailMessage

import pytest
from api.config import Settings
from api.dependencies.auth import build_mailer
from api.mailer import LoggingMailer, SmtpMailer
from app_core.account.application.registration import MailDeliveryError

SMTP_RECIPIENT = "alex@example.com"
SMTP_SECRET = "sekret-token-123"


class FakeSMTP:
    """smtplib.SMTP stand-in that records the last delivery attempt."""

    fail_with: Exception | None = None
    instances: list["FakeSMTP"] = []

    def __init__(self, *args: object, **kwargs: object) -> None:
        if FakeSMTP.fail_with is not None:
            raise FakeSMTP.fail_with
        self.sent: list[EmailMessage] = []
        self.login_args: tuple[str, str] | None = None
        self.starttls_calls = 0
        FakeSMTP.instances.append(self)

    def __enter__(self) -> "FakeSMTP":
        return self

    def __exit__(self, *args: object) -> bool:
        return False

    def ehlo(self) -> None: ...

    def starttls(self) -> None:
        self.starttls_calls += 1

    def login(self, username: str, password: str) -> None:
        self.login_args = (username, password)

    def send_message(self, message: EmailMessage) -> None:
        self.sent.append(message)


@pytest.fixture(autouse=True)
def fake_smtp(monkeypatch: pytest.MonkeyPatch) -> FakeSMTP:
    FakeSMTP.fail_with = None
    FakeSMTP.instances = []
    monkeypatch.setattr(smtplib, "SMTP", FakeSMTP)
    return FakeSMTP


def make_mailer(**overrides: object) -> SmtpMailer:
    base: dict[str, object] = {
        "host": "smtp.example.com",
        "port": 587,
        "from_addr": "no-reply@moyu.docs",
        "link_base_url": "https://app.moyu.docs",
    }
    base.update(overrides)
    return SmtpMailer(**base)  # type: ignore[arg-type]


def test_smtp_mailer_verification_delivers_link() -> None:
    mailer = make_mailer()
    import asyncio

    asyncio.run(mailer.send_verification(SMTP_RECIPIENT, SMTP_SECRET))
    assert FakeSMTP.instances, "SMTP connection must be attempted"
    instance = FakeSMTP.instances[0]
    assert len(instance.sent) == 1
    message = instance.sent[0]
    assert message["To"] == SMTP_RECIPIENT
    assert message["From"] == "no-reply@moyu.docs"
    assert "验证您的邮箱" in message["Subject"]
    assert (
        f"https://app.moyu.docs/verify-email?token={SMTP_SECRET}"
        in message.get_body().get_content()
    )


def test_smtp_mailer_password_reset_delivers_link() -> None:
    mailer = make_mailer()
    import asyncio

    asyncio.run(mailer.send_password_reset(SMTP_RECIPIENT, SMTP_SECRET))
    instance = FakeSMTP.instances[0]
    message = instance.sent[0]
    assert "重置您的密码" in message["Subject"]
    assert (
        f"https://app.moyu.docs/reset-password?token={SMTP_SECRET}"
        in message.get_body().get_content()
    )


def test_smtp_mailer_starttls_and_optional_login() -> None:
    mailer = make_mailer(username="relay.user", password="relay-pass")
    import asyncio

    asyncio.run(mailer.send_verification(SMTP_RECIPIENT, SMTP_SECRET))
    instance = FakeSMTP.instances[0]
    assert instance.starttls_calls == 1
    assert instance.login_args == ("relay.user", "relay-pass")


def test_smtp_mailer_starttls_disabled() -> None:
    mailer = make_mailer(starttls=False)
    import asyncio

    asyncio.run(mailer.send_verification(SMTP_RECIPIENT, SMTP_SECRET))
    assert FakeSMTP.instances[0].starttls_calls == 0


def test_smtp_delivery_failure_surfaces_mail_delivery_error() -> None:
    FakeSMTP.fail_with = smtplib.SMTPException("greeting refused")
    mailer = make_mailer()
    import asyncio

    with pytest.raises(MailDeliveryError):
        asyncio.run(mailer.send_verification(SMTP_RECIPIENT, SMTP_SECRET))


def test_build_mailer_defaults_to_logging() -> None:
    assert isinstance(build_mailer(Settings(mailer_provider="logging")), LoggingMailer)


def test_build_mailer_smtp_gate_requires_host_and_from() -> None:
    with pytest.raises(RuntimeError, match=r"SMTP_HOST/SMTP_FROM"):
        build_mailer(Settings(mailer_provider="smtp"))


def test_build_mailer_smtp_partial_config_is_rejected() -> None:
    with pytest.raises(RuntimeError, match=r"SMTP_FROM"):
        build_mailer(Settings(mailer_provider="smtp", smtp_host="smtp.example.com"))


def test_build_mailer_smtp_returns_smtp_mailer() -> None:
    mailer = build_mailer(
        Settings(
            mailer_provider="smtp",
            smtp_host="smtp.example.com",
            smtp_from="no-reply@moyu.docs",
            mail_link_base_url="https://app.moyu.docs",
        )
    )
    assert isinstance(mailer, SmtpMailer)
    assert mailer._host == "smtp.example.com"  # noqa: SLF001


def test_build_mailer_rejects_unknown_provider() -> None:
    with pytest.raises(RuntimeError, match=r"unknown MAILER_PROVIDER"):
        build_mailer(Settings(mailer_provider="carrier-pigeon"))
