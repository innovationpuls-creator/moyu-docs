from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import uuid4

from app_core.session.domain.session import (
    Session,
    SessionInvalidationReason,
    SessionPolicy,
    SessionStatus,
)

NOW = datetime(2026, 9, 22, tzinfo=timezone.utc)


def make_session(
    *,
    created_at: datetime,
    last_seen_at: datetime | None = None,
    device_id: str | None = None,
) -> Session:
    return Session.create(
        account_id=uuid4(),
        device_id=device_id or f"device-{uuid4()}",
        at=created_at,
        last_seen_at=last_seen_at,
    )


def test_active_session_expires_after_thirty_idle_days() -> None:
    session = make_session(
        created_at=NOW - timedelta(days=29),
        last_seen_at=NOW - timedelta(days=30),
    )

    assert session.is_active(NOW) is False
    assert session.status is SessionStatus.EXPIRED
    assert session.invalidation_reason is SessionInvalidationReason.EXPIRED


def test_active_session_expires_after_ninety_absolute_days() -> None:
    session = make_session(
        created_at=NOW - timedelta(days=90), last_seen_at=NOW - timedelta(days=1)
    )

    assert session.is_active(NOW) is False
    assert session.status is SessionStatus.EXPIRED


def test_recent_reauthentication_is_valid_for_ten_minutes() -> None:
    session = make_session(created_at=NOW)
    session.reauthenticate(NOW - timedelta(minutes=10))

    assert session.has_recent_reauthentication(NOW) is True
    assert session.has_recent_reauthentication(NOW + timedelta(microseconds=1)) is False


def test_account_deleted_reason_hydrates_revoked_sessions() -> None:
    assert (
        SessionInvalidationReason("AccountDeleted")
        is SessionInvalidationReason.ACCOUNT_DELETED
    )
    session = make_session(created_at=NOW)
    session.invalidate(
        SessionStatus.REVOKED, SessionInvalidationReason.ACCOUNT_DELETED, NOW
    )

    assert session.status is SessionStatus.REVOKED
    assert session.invalidation_reason is SessionInvalidationReason.ACCOUNT_DELETED
    assert session.is_active(NOW) is False


def test_session_policy_replaces_oldest_active_session_by_creation_time() -> None:
    oldest = make_session(
        created_at=NOW - timedelta(days=2), last_seen_at=NOW - timedelta(minutes=1)
    )
    newer = make_session(
        created_at=NOW - timedelta(days=1), last_seen_at=NOW - timedelta(days=20)
    )
    incoming = make_session(created_at=NOW)

    replaced = SessionPolicy.enforce_device_limit(
        [oldest, newer, incoming], incoming, at=NOW
    )

    assert replaced == [oldest]
    assert oldest.status is SessionStatus.REPLACED
    assert oldest.invalidation_reason is SessionInvalidationReason.NEW_DEVICE_LOGIN
    assert oldest.replaced_by_session_id == incoming.session_id
    assert newer.is_active(NOW) is True
    assert incoming.is_active(NOW) is True


def test_same_device_relogin_replaces_old_session_and_keeps_other_devices() -> None:
    old_same_device = make_session(
        created_at=NOW - timedelta(days=2), device_id="laptop"
    )
    other_device = make_session(created_at=NOW - timedelta(days=1), device_id="phone")
    incoming = make_session(created_at=NOW, device_id="laptop")

    replaced = SessionPolicy.enforce_device_limit(
        [old_same_device, other_device, incoming], incoming, at=NOW
    )

    assert replaced == [old_same_device]
    assert old_same_device.status is SessionStatus.REPLACED
    assert (
        old_same_device.invalidation_reason
        is SessionInvalidationReason.NEW_DEVICE_LOGIN
    )
    assert old_same_device.replaced_by_session_id == incoming.session_id
    assert other_device.is_active(NOW) is True
    assert incoming.is_active(NOW) is True


def test_session_policy_counts_distinct_devices_when_enforcing_quota() -> None:
    old_same_device = make_session(
        created_at=NOW - timedelta(days=3), device_id="tablet"
    )
    newer_same_device = make_session(
        created_at=NOW - timedelta(days=2), device_id="tablet"
    )
    other_device = make_session(created_at=NOW - timedelta(days=1), device_id="phone")
    incoming = make_session(created_at=NOW, device_id="desktop")

    replaced = SessionPolicy.enforce_device_limit(
        [old_same_device, newer_same_device, other_device, incoming],
        incoming,
        at=NOW,
    )

    # quota counts devices, not rows: tablet + phone + desktop = 3 devices,
    # so the oldest distinct-device survivor (newest tablet session) is replaced
    # while the older tablet session and the phone session remain active.
    assert replaced == [newer_same_device]
    assert newer_same_device.status is SessionStatus.REPLACED
    assert old_same_device.is_active(NOW) is True
    assert other_device.is_active(NOW) is True
    assert incoming.is_active(NOW) is True


def test_logout_only_invalidates_current_session_and_is_idempotent() -> None:
    logged_out = make_session(created_at=NOW)
    unaffected = make_session(created_at=NOW)

    logged_out.logout(NOW)
    logged_out.logout(NOW + timedelta(seconds=1))

    assert logged_out.is_active(NOW) is False
    assert logged_out.status is SessionStatus.LOGGED_OUT
    assert logged_out.invalidation_reason is SessionInvalidationReason.USER_LOGOUT
    assert unaffected.is_active(NOW) is True
