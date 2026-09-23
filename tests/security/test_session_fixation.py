"""Phase 9 Task 28: session fixation defense (FR-AUTH-008, AC-008.2).

The login endpoint must ALWAYS rotate the session credential: a client
claiming an arbitrary (attacker-chosen) ``dom_session`` cookie value must
never get that value accepted, and the server hands out a fresh
server-issued session id on every login. The old credential is rejected
afterward (replaced by the same-device slot, FR-AUTH-015).

Probes run against the real API app (real Postgres + real Valkey); the
attacker-supplied value is a syntactically valid UUID that was never issued,
so the test proves the server neither trusts nor persists client-claimed
session ids.
"""

from __future__ import annotations

from collections.abc import Callable
from uuid import UUID, uuid4

from httpx import AsyncClient, Response
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

VALID_PASSWORD = "Str0ng#Passw0rd"

# Mirrors tests/security/conftest.py.ClientFactory (parameter annotation only;
# the fixture is resolved by name, never imported across conftest modules).
ClientFactory = Callable[..., AsyncClient]


def _session_cookie_value(response: Response) -> str:
    for line in response.headers.get_list("set-cookie"):
        if line.split("=", 1)[0].strip() == "dom_session":
            return line.split("=", 1)[1].split(";", 1)[0].strip()
    return ""


async def _register(client: AsyncClient, email: str) -> str:
    response = await client.post(
        "/v1/auth/register", json={"email": email, "password": VALID_PASSWORD}
    )
    assert response.status_code == 201
    return _session_cookie_value(response)


async def _login(client: AsyncClient, email: str) -> tuple[int, str]:
    response = await client.post(
        "/v1/auth/login", json={"email": email, "password": VALID_PASSWORD}
    )
    return response.status_code, _session_cookie_value(response)


async def _me_with_cookie(client_factory: ClientFactory, cookie: str) -> int:
    async with client_factory(cookies={"dom_session": cookie}) as probe:
        return (await probe.get("/v1/auth/me")).status_code


async def test_login_rotates_attacker_supplied_preauth_cookie(
    client_factory: ClientFactory,
    db_session: AsyncSession,
) -> None:
    email = "fixation-rotated@example.com"
    attacker_value = str(uuid4())  # well-formed UUID the server never issued
    async with client_factory() as client:
        s1 = await _register(client, email)

        # Attacker pre-auth: the jar carries an attacker-chosen session cookie
        # when the login request is sent (AC-008.2 fixation attempt).
        client.cookies.set("dom_session", attacker_value)
        status, s2 = await _login(client, email)

    assert status == 200
    # The credential was rotated: the server ignored the claimed value and
    # issued a NEW session id, different from both the attacker value and any
    # previously issued credential.
    assert s2 != attacker_value
    assert s2 != s1
    UUID(s2)

    # The attacker-supplied value was never accepted nor persisted.
    count = await db_session.scalar(
        text("SELECT count(*) FROM auth.sessions WHERE session_id = :sid"),
        {"sid": UUID(attacker_value)},
    )
    assert int(count or 0) == 0

    # Never accepted afterward: the attacker cookie alone is rejected.
    assert await _me_with_cookie(client_factory, attacker_value) == 401
    # The rotated credential works...
    assert await _me_with_cookie(client_factory, s2) == 200
    # ...and the pre-attack session was replaced by the same-device rotation.
    assert await _me_with_cookie(client_factory, s1) == 401


async def test_every_login_rotates_the_session_credential(
    client_factory: ClientFactory,
) -> None:
    """AC-008.2: each login hands out a fresh session id; the previous one is
    immediately unusable (replaced on the same device slot)."""
    email = "fixation-rotation-every-login@example.com"
    async with client_factory() as client:
        s1 = await _register(client, email)
        status2, s2 = await _login(client, email)
        status3, s3 = await _login(client, email)

    assert status2 == 200
    assert status3 == 200
    assert len({s1, s2, s3}) == 3  # all distinct credentials

    assert await _me_with_cookie(client_factory, s3) == 200
    assert await _me_with_cookie(client_factory, s2) == 401
    assert await _me_with_cookie(client_factory, s1) == 401


async def test_server_ignores_cookie_claimed_session_on_login(
    client_factory: ClientFactory,
    db_session: AsyncSession,
) -> None:
    """The login result is derived from the credential check only: a
    client-claimed session cookie never influences which session is issued."""
    email = "fixation-influence@example.com"
    claimed = str(uuid4())
    async with client_factory() as client:
        await _register(client, email)
        client.cookies.set("dom_session", claimed)
        status, issued = await _login(client, email)

    assert status == 200
    assert issued != claimed
    # Exactly one session exists for the account: the server-issued one.
    rows = (
        (
            await db_session.execute(
                text(
                    "SELECT s.session_id, s.status FROM auth.sessions s "
                    "JOIN auth.accounts a ON a.account_id = s.account_id "
                    "WHERE a.normalized_email = :email"
                ),
                {"email": email.casefold()},
            )
        )
        .mappings()
        .all()
    )
    # The server-issued session is the only ACTIVE one; the registration
    # session was rotated away (Replaced) by the same-device slot rule. The
    # claimed cookie never influenced the outcome (no row for it).
    active_ids = [str(row["session_id"]) for row in rows if row["status"] == "Active"]
    assert active_ids == [issued]
    assert all(row["status"] == "Replaced" for row in rows if row["status"] != "Active")
