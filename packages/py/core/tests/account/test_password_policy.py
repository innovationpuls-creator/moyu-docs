from __future__ import annotations

import pytest
from app_core.account.domain.password_policy import PasswordHasher, PasswordPolicy
from app_core.common.exceptions import ValidationError


@pytest.mark.parametrize("password", ["short-pass1", "x" * 129])
def test_password_policy_rejects_passwords_outside_12_to_128_characters(
    password: str,
) -> None:
    with pytest.raises(ValidationError) as error:
        PasswordPolicy.validate(password)

    assert error.value.category == "Validation"
    assert error.value.error_code == "PASSWORD_TOO_WEAK"


def test_password_policy_rejects_common_or_breached_passwords() -> None:
    with pytest.raises(ValidationError) as error:
        PasswordPolicy.validate("password1234")

    assert error.value.error_code == "PASSWORD_TOO_WEAK"


def test_password_policy_keeps_distinct_messages_for_one_registry_code() -> None:
    with pytest.raises(ValidationError) as length_error:
        PasswordPolicy.validate("short-pass1")
    with pytest.raises(ValidationError) as breached_error:
        PasswordPolicy.validate("password1234")

    assert length_error.value.error_code == "PASSWORD_TOO_WEAK"
    assert breached_error.value.error_code == "PASSWORD_TOO_WEAK"
    assert length_error.value.message != breached_error.value.message


def test_password_hasher_uses_argon2id_and_rejects_wrong_passwords() -> None:
    password = "A unique passphrase 2026"
    password_hash = PasswordHasher.hash(password)

    assert password_hash.startswith("$argon2id$")
    assert PasswordHasher.verify(password, password_hash) is True
    assert PasswordHasher.verify("different password", password_hash) is False
