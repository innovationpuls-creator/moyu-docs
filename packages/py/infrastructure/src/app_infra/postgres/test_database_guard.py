from __future__ import annotations

from urllib.parse import urlparse

ISOLATED_TEST_DATABASE = "dom_workspace_lifecycle_test"


def require_isolated_database(database_url: str) -> str:
    parsed = urlparse(database_url.replace("postgresql+psycopg://", "postgresql://", 1))
    if parsed.path.lstrip("/") != ISOLATED_TEST_DATABASE:
        raise ValueError(f"DATABASE_URL must target {ISOLATED_TEST_DATABASE}")
    return database_url
