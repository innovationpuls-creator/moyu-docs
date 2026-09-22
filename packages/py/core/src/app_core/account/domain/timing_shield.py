from __future__ import annotations

import os

from argon2.low_level import Type, hash_secret


class TimingShield:
    """Equalizes Argon2id work across public auth entry points (FR-AUTH-007).

    Registration, forgot-password and login must not reveal whether an email
    exists through response timing. Paths that cannot perform the real
    credential work (existing-email registration, missing-email forgot
    password) compensate by running an Argon2id hash of a fixed dummy
    password; login already verifies against a precomputed dummy hash when the
    account hash is unknown.
    """

    # Fixed, non-secret dummy password. It is not a credential: login still
    # rejects even when an attacker supplies it (the account record is absent),
    # so publishing it leaks nothing (see `_invalid_credentials` in
    # authentication.py).
    DUMMY_PASSWORD: str = "dom-anti-enumeration-dummy-2026"

    # Precomputed Argon2id hash of DUMMY_PASSWORD at the SAME cost parameters
    # as real account hashes (PasswordHasher defaults), so that an unknown-email
    # login verify costs the same as a real-hash verify.
    DUMMY_PASSWORD_HASH: str = (
        "$argon2id$v=19$m=65536,t=3,p=4$tCoGCumxrEQ7FGGOQzFfbg$"
        "OJ7PJ/54iULdWFJ7ysl+jzPlzby2eiC4WA9UmnxCEVk"
    )

    # Dummy-hash cost floor: a single hash of 192 MiB / 3 passes / 4 lanes.
    # Measured ~0.08s on the reference machine (3x a default hash), so the
    # account-missing paths stay in the same duration magnitude as the real
    # paths, which carry several DB writes and a mailer call on top of the
    # password hash.
    _DUMMY_MEMORY_COST = 196608
    _DUMMY_TIME_COST = 3
    _DUMMY_PARALLELISM = 4

    @staticmethod
    def perform_dummy_hash() -> None:
        """Compute an Argon2id hash of the fixed dummy password (constant work)."""
        hash_secret(
            TimingShield.DUMMY_PASSWORD.encode(),
            os.urandom(16),
            time_cost=TimingShield._DUMMY_TIME_COST,
            memory_cost=TimingShield._DUMMY_MEMORY_COST,
            parallelism=TimingShield._DUMMY_PARALLELISM,
            hash_len=32,
            type=Type.ID,
        )


UNIFORM_AUTH_MESSAGES: dict[str, str] = {
    # Canonical user-facing copy (PRD FR-AUTH-007 / docs/behavior/features/
    # account-auth-session.feature). The Phase 7 API boundary selects these for
    # external responses so no public endpoint reveals email existence.
    "REGISTER_SUCCESS": "如果该邮箱可以继续注册，请检查邮箱中的后续指引",
    "FORGOT_PASSWORD_SUCCESS": "如果该邮箱已注册，重置密码邮件已发送",
    "INVALID_CREDENTIALS": "邮箱或密码错误",
    # Code-level English variants: stable domain strings asserted by existing
    # unit/infrastructure tests; use cases source them from this dict so there
    # is exactly one definition per message.
    "REGISTER_SUCCESS_EN": (
        "If this email can continue registration, check your email for next steps."
    ),
    "FORGOT_PASSWORD_SUCCESS_EN": (
        "If this email is registered, a reset email has been sent."
    ),
    "INVALID_CREDENTIALS_EN": "Invalid credentials.",
}
