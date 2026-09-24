import pytest
from app_infra.postgres.test_database_guard import require_isolated_database


@pytest.mark.parametrize(
    "database_url",
    [
        "postgresql+psycopg://torch@localhost:5432/dom_dev",
        "postgresql+psycopg://torch@localhost:5432/dom_workspace_lifecycle_test_copy",
    ],
)
def test_guard_rejects_non_isolated_database(database_url: str) -> None:
    with pytest.raises(ValueError, match="dom_workspace_lifecycle_test"):
        require_isolated_database(database_url)
