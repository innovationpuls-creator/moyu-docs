"""Phase 9 Task 28: anti-enumeration response uniformity (Review Focus #2).

Covers the uniform-response + timing-magnitude requirements for the three
public auth entry points (FR-AUTH-005/007, PRD cross-requirement invariant 6):

- register: 201 + identical body for existing vs missing emails (USER RULING
  2026-09-23; the Set-Cookie oracle is an accepted, rate-limited residual).
- login: identical 401 INVALID_CREDENTIALS envelope for wrong-password vs
  unknown-email (no email-existence leak).
- forgot-password: identical 200 uniform body for registered vs unregistered
  emails (FR-AUTH-024).
- timing magnitude: the unknown-email login completes with comparable
  wall-clock magnitude (loose, non-flaky bounds): a lower bound proves the
  TimingShield dummy-hash runs instead of a fast short-circuit, and generous
  upper bounds avoid CI flakes.

All API traffic runs against the real Postgres + real Valkey via the
services/api conftest fixtures (tests/security/conftest.py).
"""

from __future__ import annotations

import time
from typing import Any

from httpx import AsyncClient

VALID_PASSWORD = "Str0ng#Passw0rd"  # 14 chars, BDD FR-AUTH-001


def _uniform_login_envelope(body: dict[str, Any]) -> dict[str, Any]:
    """Normalize a login error envelope for equality checks: requestId is
    per-request random and must not break the uniformity comparison."""
    normalized = dict(body)
    normalized.pop("requestId", None)
    return normalized


async def test_register_uniform_201_for_existing_and_missing_email(
    api_client: AsyncClient,
) -> None:
    known = "uniform-register@example.com"
    missing = "uniform-register-missing@example.com"

    first = await api_client.post(
        "/v1/auth/register", json={"email": known, "password": VALID_PASSWORD}
    )
    repeat = await api_client.post(
        "/v1/auth/register", json={"email": known, "password": VALID_PASSWORD}
    )
    fresh = await api_client.post(
        "/v1/auth/register", json={"email": missing, "password": VALID_PASSWORD}
    )

    # Existing vs missing: identical status and identical body structure.
    assert first.status_code == 201
    assert repeat.status_code == 201
    assert fresh.status_code == 201
    assert set(repeat.json().keys()) == set(fresh.json().keys())
    assert repeat.json()["messageKey"] == fresh.json()["messageKey"]
    # The repeated (existing) registration echoes the SAME full body because
    # the probe email is identical; the missing path differs only in the
    # echoed email address, never in status/message.
    assert repeat.json() == first.json()
    assert fresh.json()["messageKey"] == first.json()["messageKey"]


async def test_login_unknown_email_identical_401_to_wrong_password(
    api_client: AsyncClient,
) -> None:
    known = "uniform-login@example.com"
    response = await api_client.post(
        "/v1/auth/register", json={"email": known, "password": VALID_PASSWORD}
    )
    assert response.status_code == 201

    wrong_password = await api_client.post(
        "/v1/auth/login",
        json={"email": known, "password": "Wrong!Password"},
    )
    unknown_email = await api_client.post(
        "/v1/auth/login",
        json={"email": "uniform-login-missing@example.com", "password": "Whatever1!"},
    )

    assert wrong_password.status_code == 401
    assert unknown_email.status_code == 401
    assert _uniform_login_envelope(wrong_password.json()) == _uniform_login_envelope(
        unknown_email.json()
    )
    body = wrong_password.json()
    assert body["category"] == "Authentication"
    assert body["errorCode"] == "INVALID_CREDENTIALS"


async def test_forgot_password_uniform_200_for_registered_and_missing(
    api_client: AsyncClient,
) -> None:
    known = "uniform-forgot@example.com"
    response = await api_client.post(
        "/v1/auth/register", json={"email": known, "password": VALID_PASSWORD}
    )
    assert response.status_code == 201

    registered = await api_client.post(
        "/v1/auth/forgot-password", json={"email": known}
    )
    missing = await api_client.post(
        "/v1/auth/forgot-password", json={"email": "uniform-forgot-missing@example.com"}
    )

    assert registered.status_code == 200
    assert missing.status_code == 200
    assert set(registered.json().keys()) == set(missing.json().keys())
    assert registered.json()["messageKey"] == missing.json()["messageKey"]
    # Both responses advertise the next-allowed timestamp (FR-AUTH-004/024
    # cooldown copy) regardless of whether the email exists.
    assert registered.json()["nextAllowedAt"] is not None
    assert missing.json()["nextAllowedAt"] is not None


async def test_login_timing_magnitude_unknown_email_not_fast_path(
    api_client: AsyncClient,
) -> None:
    """Loose, non-flaky timing-magnitude check (FR-AUTH-007 耗时量级一致).

    The unknown-email login must perform comparable work to the wrong-password
    path (Argon2id dummy hash instead of a fast short-circuit). Bounds are
    deliberately generous (5ms lower bound, 15s upper, 10x ratio) so they
    cannot flake in CI; the previous tests already prove the responses are
    structurally identical.
    """
    known = "uniform-timing@example.com"
    response = await api_client.post(
        "/v1/auth/register", json={"email": known, "password": VALID_PASSWORD}
    )
    assert response.status_code == 201

    async def _elapsed(email: str) -> float:
        started = time.perf_counter()
        probe = await api_client.post(
            "/v1/auth/login",
            json={"email": email, "password": "Wrong!Password"},
        )
        assert probe.status_code == 401
        return time.perf_counter() - started

    # Two samples per branch, median-ordered.
    unknown_samples = sorted([await _elapsed(known), await _elapsed(known)])
    missing_samples = sorted(
        [
            await _elapsed("uniform-timing-missing@example.com"),
            await _elapsed("uniform-timing-missing@example.com"),
        ]
    )
    unknown_median = unknown_samples[1]
    missing_median = missing_samples[1]

    # The missing-email path did real crypto work (not a microsecond
    # short-circuit) and both branches stay within generous bounds.
    assert missing_median > 0.005
    assert missing_median < 15.0
    assert unknown_median < 15.0
    lower, upper = sorted([unknown_median, missing_median])
    assert upper / lower < 10.0
