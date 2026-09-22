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


settings = Settings()
