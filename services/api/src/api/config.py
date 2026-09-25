"""Runtime configuration for the DOM API service.

Phase 7 bootstrap: values come from environment variables with monorepo-dev
defaults. ``contracts_dir`` resolves the canonical contract sources (doc 28)
relative to the repo; the error-envelope handler reads
``contracts/errors/error-codes.yaml`` from there (doc 28 §28).
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

# services/api/src/api/config.py -> repo root.
_REPO_ROOT = Path(__file__).resolve().parents[4]


@dataclass
class Settings:
    # Mirrored into ``create_app(debug=...)``; controls whether auth cookies
    # get the Secure attribute (Secure only outside debug, plan Task 20).
    debug: bool = False
    valkey_url: str = field(
        default_factory=lambda: os.getenv("VALKEY_URL", "redis://localhost:6379/14")
    )
    contracts_dir: Path = field(
        default_factory=lambda: Path(
            os.getenv("CONTRACTS_DIR", str(_REPO_ROOT / "contracts"))
        )
    )
    # Auth cookie names (doc 16 §30-§33, §97): minimal Path/Scope.
    session_cookie: str = "dom_session"
    device_cookie: str = "dom_device"
    # Device cookie lifetime: stable per browser across sessions (FR-AUTH-013).
    device_cookie_max_age: int = 10 * 365 * 24 * 60 * 60

    # Mailer provider (doc 16 §51): "logging" = dev log delivery (default);
    # "smtp" = real SMTP delivery. In smtp mode SMTP_HOST/SMTP_FROM are
    # required and validated by the wiring gate; MAIL_LINK_BASE_URL is the
    # public origin embedded in mail links.
    mailer_provider: str = field(
        default_factory=lambda: os.getenv("MAILER_PROVIDER", "logging").strip().lower()
    )
    smtp_host: str | None = field(
        default_factory=lambda: os.getenv("SMTP_HOST") or None
    )
    smtp_port: int = field(default_factory=lambda: int(os.getenv("SMTP_PORT", "587")))
    smtp_username: str | None = field(
        default_factory=lambda: os.getenv("SMTP_USERNAME") or None
    )
    smtp_password: str | None = field(
        default_factory=lambda: os.getenv("SMTP_PASSWORD") or None
    )
    smtp_from: str | None = field(
        default_factory=lambda: os.getenv("SMTP_FROM") or None
    )
    smtp_starttls: bool = field(
        default_factory=lambda: (
            os.getenv("SMTP_STARTTLS", "1") not in {"0", "false", "False"}
        )
    )
    mail_link_base_url: str = field(
        default_factory=lambda: os.getenv("MAIL_LINK_BASE_URL", "http://localhost:5173")
    )
    invitation_idempotency_encryption_key: str | None = field(
        default_factory=lambda: os.getenv("INVITATION_IDEMPOTENCY_ENCRYPTION_KEY")
    )
    share_link_idempotency_encryption_key: str | None = field(
        default_factory=lambda: os.getenv("SHARE_LINK_IDEMPOTENCY_ENCRYPTION_KEY")
    )


settings = Settings()
