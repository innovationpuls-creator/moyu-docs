from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

import pytest
from app_core.account.domain.account import Account, AccountStatus
from app_core.common.exceptions import AuthenticationError


def test_email_account_starts_pending_verification_with_stable_identity() -> None:
    account = Account.create_with_email("Alice@Example.com")

    assert isinstance(account.account_id, UUID)
    assert account.primary_email == "Alice@Example.com"
    assert account.normalized_email == "alice@example.com"
    assert account.status is AccountStatus.PENDING_VERIFICATION
    assert account.can_enter_product() is True
    assert account.can_create_workspace() is False
    assert account.can_login() is True


def test_email_verification_activates_account_and_unlocks_workspace_creation() -> None:
    account = Account.create_with_email("alice@example.com")

    account.verify_email(at=datetime(2026, 9, 22, tzinfo=timezone.utc))

    assert account.status is AccountStatus.ACTIVE
    assert account.email_verified_at == datetime(2026, 9, 22, tzinfo=timezone.utc)
    assert account.can_create_workspace() is True


def test_disabled_or_deleted_account_cannot_login_or_be_verified() -> None:
    account = Account.create_with_email("alice@example.com")
    account.disable()

    assert account.can_login() is False
    with pytest.raises(AuthenticationError):
        account.verify_email()

    account.purge()
    assert account.status is AccountStatus.DELETED
    assert account.can_enter_product() is False


def test_cancelling_deletion_restores_exact_prior_account_status() -> None:
    active = Account.create_with_email("active@example.com")
    active.verify_email()
    active.request_deletion()
    assert active.status is AccountStatus.DELETION_PENDING
    assert active.can_enter_product() is True
    assert active.can_create_workspace() is False

    active.cancel_deletion()
    assert active.status is AccountStatus.ACTIVE

    pending = Account.create_with_email("pending@example.com")
    pending.request_deletion()
    pending.cancel_deletion()
    assert pending.status is AccountStatus.PENDING_VERIFICATION


def test_deletion_pending_allows_login_but_only_recovery_mode() -> None:
    account = Account.create_with_email("alice@example.com")
    account.request_deletion()

    assert account.can_login() is True
    assert account.can_enter_product() is True
    assert account.is_in_recovery_mode() is True


def test_deletion_pending_account_cannot_verify_email_or_exit_recovery_mode() -> None:
    account = Account.create_with_email("alice@example.com")
    requested_at = datetime(2026, 9, 22, tzinfo=timezone.utc)
    account.request_deletion(at=requested_at)

    with pytest.raises(AuthenticationError):
        account.verify_email(at=datetime(2026, 9, 23, tzinfo=timezone.utc))

    assert account.status is AccountStatus.DELETION_PENDING
    assert account.email_verified_at is None
    assert account.updated_at == requested_at
    assert account.can_create_workspace() is False
    assert account.is_in_recovery_mode() is True


def test_deletion_request_is_idempotent_and_cannot_delete_disabled_account() -> None:
    account = Account.create_with_email("alice@example.com")
    account.request_deletion()
    original_requested_at = account.deletion_requested_at
    original_status = account.pre_deletion_status

    account.request_deletion()
    assert account.deletion_requested_at == original_requested_at
    assert account.pre_deletion_status == original_status

    disabled = Account.create_with_email("disabled@example.com")
    disabled.disable()
    with pytest.raises(AuthenticationError):
        disabled.request_deletion()
