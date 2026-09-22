from __future__ import annotations


class DomainError(Exception):
    """A domain failure that maps to a stable error category and code."""

    def __init__(self, message: str, error_code: str, category: str) -> None:
        super().__init__(message)
        self.message = message
        self.error_code = error_code
        self.category = category


class ValidationError(DomainError):
    def __init__(self, message: str, error_code: str, field: str | None = None) -> None:
        super().__init__(message, error_code, "Validation")
        self.field = field


class AuthenticationError(DomainError):
    def __init__(self, message: str, error_code: str = "ACCOUNT_UNAVAILABLE") -> None:
        super().__init__(message, error_code, "Authentication")


class NotFoundError(DomainError):
    def __init__(self, message: str, error_code: str = "NOT_FOUND") -> None:
        super().__init__(message, error_code, "NotFound")


class RateLimitError(DomainError):
    def __init__(self, message: str, error_code: str = "RATE_LIMITED") -> None:
        super().__init__(message, error_code, "RateLimit")


class PermissionDeniedError(DomainError):
    def __init__(self, message: str, error_code: str = "PERMISSION_DENIED") -> None:
        super().__init__(message, error_code, "Permission")


class ConflictError(DomainError):
    def __init__(
        self, message: str, error_code: str = "CONFLICT", field: str | None = None
    ) -> None:
        super().__init__(message, error_code, "Conflict")
        self.field = field


class DuplicateEmailError(ConflictError):
    def __init__(
        self, message: str = "An account with this email already exists."
    ) -> None:
        super().__init__(message, "EMAIL_ALREADY_EXISTS")


class IdempotencyConflictError(ConflictError):
    def __init__(
        self,
        message: str = "An idempotent request is already in progress.",
        error_code: str = "IDEMPOTENCY_KEY_CONFLICT",
    ) -> None:
        super().__init__(message, error_code)
