from __future__ import annotations

from argon2 import PasswordHasher as Argon2PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError

from app_core.common.exceptions import ValidationError

_COMMON_COMPROMISED_PASSWORDS = frozenset(
    {
        "123456789012",
        "admin1234567",
        "iloveyou1234",
        "password1234",
        "password12345",
        "qwertyuiop12",
        "welcome12345",
    }
)
_ARGON2ID_HASHER = Argon2PasswordHasher()


class PasswordPolicy:
    @staticmethod
    def validate(password: str) -> None:
        if not 12 <= len(password) <= 128:
            raise ValidationError(
                "Password must contain 12 to 128 characters.",
                "PASSWORD_TOO_WEAK",
                field="password",
            )
        if password.casefold() in _COMMON_COMPROMISED_PASSWORDS:
            raise ValidationError(
                "Password is common or known to be compromised.",
                "PASSWORD_TOO_WEAK",
                field="password",
            )


class PasswordHasher:
    @staticmethod
    def hash(password: str) -> str:
        return _ARGON2ID_HASHER.hash(password)

    @staticmethod
    def verify(password: str, password_hash: str) -> bool:
        try:
            return _ARGON2ID_HASHER.verify(password_hash, password)
        except (InvalidHashError, VerificationError):
            return False
