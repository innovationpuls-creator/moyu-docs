from datetime import UTC, datetime, timedelta
from uuid import uuid4

from app_core.workspace.application.purge import PurgePolicy
from app_core.workspace.ports.purge import PurgeCandidate, purge_effect_key


def test_eligibility_boundary_and_restored_exclusion():
    now = datetime.now(UTC)
    assert PurgePolicy.eligible(
        status="DeletionPending", purge_eligible_at=now, now=now
    )
    assert not PurgePolicy.eligible(
        status="DeletionPending", purge_eligible_at=now + timedelta(seconds=1), now=now
    )
    assert not PurgePolicy.eligible(status="Active", purge_eligible_at=now, now=now)


def test_payload_has_no_secrets_and_effect_key_is_stable():
    workspace_id = uuid4()
    payload = PurgePolicy.payload(
        PurgeCandidate(workspace_id, datetime.now(UTC))
    ).as_dict()
    assert set(payload) == {
        "workspaceId",
        "purgeEligibleAt",
        "schemaVersion",
        "handlerVersion",
    }
    assert purge_effect_key(workspace_id) == f"lifecycle.purge.workspace:{workspace_id}"
