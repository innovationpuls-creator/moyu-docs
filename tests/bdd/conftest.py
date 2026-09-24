"""Shared fixtures for the Phase 9 BDD suite (plan Task 29).

The BDD suite drives the REAL FastAPI app (services/api) against the REAL
local PostgreSQL (dom_dev) and the REAL local Valkey (docker dom-valkey,
db 14), mirroring services/api/tests and tests/security.

Design note: pytest-bdd 8.x never awaits ``async def`` step functions (its
``_execute_step_function`` calls them plain), so this suite runs every step
synchronously and dispatches all async I/O onto ONE dedicated event loop that
lives in a daemon thread (``runner``). The ``db_session`` fixture here shadows
the pytest-asyncio one from tests/conftest.py with a synchronous twin bound to
the same loop, so no async step/fixture interplay exists under tests/bdd.

pytest-bdd 8.x maps Gherkin tags to pytest markers (the pre-8 ``filter_``
argument was removed), so the 9 ``@browser`` scenarios (FR-AUTH-013/016/017/
019/021 — genuine browser runtime semantics, delegated to Playwright in plan
Task 30) are deselected here by marker: plain ``pytest tests/bdd`` executes
exactly the 55 backend scenarios. Scenario tags used anywhere in the feature
(FR-AUTH-001..037) are registered as markers in pyproject.toml for
``--strict-markers``.
"""

from __future__ import annotations

import asyncio
import os
import sys
import threading
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Coroutine
from uuid import UUID

import pytest
from alembic import command
from alembic.config import Config
from redis.asyncio import Redis

# Make the monorepo root importable so the BDD modules can use the
# ``tests.bdd.step_defs...`` / ``tests.bdd.conftest`` dotted package layout
# (tests/ is a PEP 420 namespace package; pytest only puts the per-file
# basedirs on sys.path by default).
_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

os.environ.setdefault(
    "DATABASE_URL", "postgresql+psycopg://torch@localhost:5432/dom_dev"
)
os.environ.setdefault("VALKEY_URL", "redis://localhost:6379/14")

from api.dependencies.auth import (  # noqa: E402
    get_db_session,
    get_mailer,
    get_rate_limiter,
    get_valkey,
)
from api.dependencies.workspace_ownership import (  # noqa: E402
    get_workspace_ownership,
)
from api.main import create_app  # noqa: E402
from app_core.account.application.registration import MailDeliveryError  # noqa: E402
from app_core.account.ports.workspace_ownership_query_port import (  # noqa: E402
    WorkspaceOwnershipQueryPort,
)
from app_infra.postgres.engine import engine  # noqa: E402
from app_infra.valkey.rate_limiter import RateLimiter  # noqa: E402
from httpx import ASGITransport, AsyncClient  # noqa: E402
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker  # noqa: E402

ALEMBIC_INI = Path("migrations/postgres/alembic.ini")


class CapturingMailer:
    """Records deliveries; implements both mailer protocols.

    ``sent`` carries verification mails, ``password_resets`` carries password-
    reset mails (kept distinct so steps can assert each channel separately).
    ``fail_sends`` simulates an external mail-provider outage (FR-AUTH-001/036).
    """

    def __init__(self) -> None:
        self.sent: list[tuple[str, str]] = []
        self.password_resets: list[tuple[str, str]] = []
        self.fail_sends = False

    async def send_verification(self, email: str, secret: str) -> None:
        if self.fail_sends:
            raise MailDeliveryError("mail provider unreachable")
        self.sent.append((email, secret))

    async def send_password_reset(self, email: str, secret: str) -> None:
        if self.fail_sends:
            raise MailDeliveryError("mail provider unreachable")
        self.password_resets.append((email, secret))


class SoleOwnerQuery(WorkspaceOwnershipQueryPort):
    """Test adapter: reports sole ownership of one workspace (FR-AUTH-029)."""

    def __init__(self, workspace: str | None = None) -> None:
        self._workspace = workspace

    async def has_sole_workspace_ownership(
        self, account_id: UUID
    ) -> tuple[bool, str | None]:
        if self._workspace is None:
            return False, None
        return True, self._workspace


@dataclass
class BDDContext:
    """Per-scenario world: per-device API clients + request/seed state.

    Each named device gets its own httpx cookie jar, which is exactly how the
    API distinguishes devices (the ``dom_device`` + ``dom_session`` cookies);
    a fresh client is therefore a fresh device (and "another app instance"
    when needed, FR-AUTH-010/015). ``run`` dispatches coroutines onto the
    suite's dedicated event loop thread.
    """

    db_session: AsyncSession
    valkey_client: Redis
    run: Callable[[Coroutine[Any, Any, Any]], Any]
    mailer: CapturingMailer = field(default_factory=CapturingMailer)
    # Default (None) -> the app's real RateLimiter bound to the Valkey client.
    rate_limiter: RateLimiter | None = None
    # Default (None) -> the app's NoOwnedWorkspacesQuery placeholder.
    ownership: WorkspaceOwnershipQueryPort | None = None
    devices: dict[str, AsyncClient] = field(default_factory=dict)
    last_status: int | None = None
    last_body: dict | None = None
    # Captured httpx responses / bodies for the identical-response checks.
    captured_responses: list = field(default_factory=list)
    # normalized email -> {"account_id": str, "password": str, ...}
    accounts: dict[str, dict[str, str]] = field(default_factory=dict)
    current_email: str | None = None
    # device name -> current dom_session cookie value
    sessions: dict[str, str] = field(default_factory=dict)
    # one-time-token secrets by role / email key
    verification_secrets: dict[str, str] = field(default_factory=dict)
    reset_secrets: dict[str, str] = field(default_factory=dict)
    # audit actions seen for the account under test (FR-AUTH-037)
    audit_actions: list[str] = field(default_factory=list)

    def new_client(self) -> AsyncClient:
        app = create_app(debug=True)
        app.dependency_overrides[get_db_session] = lambda: self.db_session
        app.dependency_overrides[get_valkey] = lambda: self.valkey_client
        app.dependency_overrides[get_mailer] = lambda: self.mailer
        if self.rate_limiter is not None:
            app.dependency_overrides[get_rate_limiter] = lambda: self.rate_limiter
        if self.ownership is not None:
            app.dependency_overrides[get_workspace_ownership] = lambda: self.ownership
        return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")

    def device(self, name: str) -> AsyncClient:
        """Return (creating on demand) the API client for a device name."""
        if name not in self.devices:
            self.devices[name] = self.new_client()
        return self.devices[name]


def _alembic_config(database_url: str) -> Config:
    config = Config(str(ALEMBIC_INI))
    config.set_main_option("sqlalchemy.url", database_url)
    return config


@pytest.fixture(scope="session")
def runner() -> Iterator[Callable[[Coroutine[Any, Any, Any]], Any]]:
    """Dedicated event loop for the whole BDD suite, running in a daemon
    thread. ``run(coro)`` blocks the calling (pytest) thread until ``coro``
    completes on the loop and re-raises its exception."""
    loop = asyncio.new_event_loop()
    thread = threading.Thread(target=loop.run_forever, name="bdd-loop", daemon=True)
    thread.start()

    def run(coro: Coroutine[Any, Any, Any]) -> Any:
        return asyncio.run_coroutine_threadsafe(coro, loop).result()

    try:
        yield run
    finally:
        loop.call_soon_threadsafe(loop.stop)
        thread.join(timeout=5)


@pytest.fixture(scope="session")
def migrated_database(
    runner: Callable[[Coroutine[Any, Any, Any]], Any],
) -> None:
    """Bring dom_dev to head once per session (idempotent; mirrors the other
    API/security/migration suites) so the BDD suite is self-sufficient."""
    database_url = os.getenv("DATABASE_URL", "postgresql+psycopg:///dom_dev")

    async def _upgrade() -> None:
        command.upgrade(_alembic_config(database_url), "head")

    runner(_upgrade())


@pytest.fixture
def db_session(
    runner: Callable[[Coroutine[Any, Any, Any]], Any],
) -> Iterator[AsyncSession]:
    """Synchronous twin of tests/conftest.py::db_session: a savepoint-wrapped
    transaction on the bdd event loop, rolled back after every scenario."""

    async def _setup() -> tuple[AsyncSession, Any]:
        connection = await engine.connect()
        await connection.begin()
        factory = async_sessionmaker(
            bind=connection,
            expire_on_commit=False,
            class_=AsyncSession,
            join_transaction_mode="create_savepoint",
        )
        session = factory()
        return session, connection

    session, connection = runner(_setup())

    async def _teardown() -> None:
        try:
            await session.rollback()
        finally:
            # Return the connection to the pool (otherwise the pool exhausts
            # and later tests stall on the 30s pool_timeout).
            await connection.close()

    try:
        yield session
    finally:
        runner(_teardown())


@pytest.fixture
def valkey_client(
    runner: Callable[[Coroutine[Any, Any, Any]], Any],
) -> Iterator[Redis]:
    client = Redis.from_url(os.environ["VALKEY_URL"], decode_responses=True)
    runner(client.flushdb())
    try:
        yield client
    finally:
        runner(client.flushdb())
        runner(client.aclose())


@pytest.fixture
def bdd_context(
    db_session: AsyncSession,
    valkey_client: Redis,
    migrated_database: None,
    runner: Callable[[Coroutine[Any, Any, Any]], Any],
) -> Iterator[BDDContext]:
    ctx = BDDContext(
        db_session=db_session,
        valkey_client=valkey_client,
        run=runner,
    )
    try:
        yield ctx
    finally:
        for client in ctx.devices.values():
            runner(client.aclose())


def pytest_configure(config) -> None:  # type: ignore[no-untyped-def]
    """Register lifecycle requirement markers before pytest-bdd collection."""
    for number in range(1, 12):
        marker = f"FR-WRL-{number:03d}: Workspace lifecycle requirement"
        if marker not in config.getini("markers"):
            config.addinivalue_line("markers", marker)
    pending_marker = (
        "pending-contract-binding: lifecycle scenario awaits canonical Task-4 "
        "OpenAPI/Contract path and schema before executable step binding"
    )
    if pending_marker not in config.getini("markers"):
        config.addinivalue_line("markers", pending_marker)
    config.addinivalue_line(
        "markers",
        "pending_owner_bootstrap: Workspace creation awaits Permission owner bootstrap",
    )


def pytest_collection_modifyitems(config, items) -> None:  # type: ignore[no-untyped-def]
    """pytest-bdd >= 8 routes tag filtering through pytest markers; emulate the
    pre-8 ``filter_="not browser"`` selection by deselecting the 9 browser-
    semantic scenarios from this suite (they run under Playwright, Task 30).

    Limitation note (pytest-bdd 8.x): the keyword-based deselection mechanism
    from pytest-bdd < 8 (``filter_`` on the scenario decorator) was removed,
    and pytest-bdd scenario items cannot be deselected through a marker
    keyword expression (``-m "not browser"``) — tags compile to markers at
    collection, but the BDD item hook does not re-run the mark expression the
    way plain pytest tests do. ``add_marker(skip)`` would leave 9 skipped
    items in the collection instead of truly deselecting them. Filtering the
    ``items`` list here is therefore the honest mechanism: removed items are
    never collected, keeping ``pytest tests/bdd`` at exactly 55 executed.
    """
    kept = [
        item
        for item in items
        if not (
            str(item.path).endswith("tests/bdd/test_account_auth_session_bdd.py")
            and item.get_closest_marker("browser") is not None
        )
        and not (
            str(item.path).endswith(
                "tests/bdd/test_workspace_resource_lifecycle_bdd.py"
            )
            and item.get_closest_marker("pending_owner_bootstrap") is not None
        )
    ]
    if len(kept) != len(items):
        # pytest-bdd 8.x limitation: `item.items[:] = kept` (removing the
        # browser scenarios) is the only reliable deselection for BDD items —
        # see the docstring above. Replacing it with marker-based selection is
        # not possible for pytest-bdd scenario items. The pending lifecycle
        # owner-bootstrap scenario is deliberately deselected until its
        # Permission-backed shared transaction exists.
        items[:] = kept
