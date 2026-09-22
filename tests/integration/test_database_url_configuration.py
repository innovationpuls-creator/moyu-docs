import importlib
import sys

from _pytest.monkeypatch import MonkeyPatch


def test_default_database_url_uses_local_postgres_socket(
    monkeypatch: MonkeyPatch,
) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)
    sys.modules.pop("app_infra.postgres.engine", None)

    engine_module = importlib.import_module("app_infra.postgres.engine")

    assert engine_module.DATABASE_URL == "postgresql+psycopg:///dom_dev"
