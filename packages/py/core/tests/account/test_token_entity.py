from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import uuid4

from app_core.account.domain.token import OneTimeToken, OneTimeTokenType

NOW = datetime(2026, 9, 22, tzinfo=timezone.utc)


def test_email_verification_token_is_hash_only_and_valid_for_a_day() -> None:
    token, secret = OneTimeToken.issue(
        account_id=uuid4(), token_type=OneTimeTokenType.EMAIL_VERIFICATION, at=NOW
    )

    assert secret not in token.token_hash
    assert token.expires_at == NOW + timedelta(hours=24)
    assert token.matches(secret, NOW + timedelta(hours=23, minutes=59)) is True
    assert token.matches(secret, NOW + timedelta(hours=24)) is False


def test_password_reset_token_is_valid_for_fifteen_minutes() -> None:
    token, secret = OneTimeToken.issue(
        account_id=uuid4(), token_type=OneTimeTokenType.PASSWORD_RESET, at=NOW
    )

    assert token.expires_at == NOW + timedelta(minutes=15)
    assert token.matches(secret, NOW + timedelta(minutes=14, seconds=59)) is True
    assert token.matches(secret, NOW + timedelta(minutes=15)) is False


def test_one_time_token_cannot_be_reused_after_consumption() -> None:
    token, secret = OneTimeToken.issue(
        account_id=uuid4(), token_type=OneTimeTokenType.PASSWORD_RESET, at=NOW
    )

    assert token.consume(secret, NOW) is True
    assert token.consumed_at == NOW
    assert token.consume(secret, NOW + timedelta(seconds=1)) is False

    assert token.matches(secret, NOW + timedelta(seconds=1)) is False
