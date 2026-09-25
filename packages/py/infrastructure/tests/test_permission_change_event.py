from __future__ import annotations

import json
from pathlib import Path
from uuid import uuid4

import pytest
from app_infra.postgres.permission_administration_repository import (
    PostgresPermissionAdministrationRepository,
)
from jsonschema import Draft202012Validator, FormatChecker
from referencing import Registry, Resource


class RecordingSession:
    def __init__(self) -> None:
        self.parameters: dict[str, object] | None = None

    async def execute(self, _statement: object, parameters: dict[str, object]) -> None:
        self.parameters = parameters


@pytest.mark.asyncio
async def test_workspace_permission_change_outbox_payload_matches_contract() -> None:
    session = RecordingSession()
    repository = PostgresPermissionAdministrationRepository(session, b"x" * 32)

    await repository._publish_permission_change(
        "workspace", uuid4(), uuid4(), None, "workspace_policy_changed", None
    )

    assert session.parameters is not None
    envelope = session.parameters["payload"]
    assert isinstance(envelope, dict)
    contracts_root = Path(__file__).resolve().parents[4] / "contracts"
    permission_schema = json.loads(
        (
            contracts_root / "events/permission/permission-changed.schema.json"
        ).read_text()
    )
    ids_schema = json.loads((contracts_root / "ids/ids.schema.json").read_text())
    registry = Registry().with_resources(
        (
            (permission_schema["$id"], Resource.from_contents(permission_schema)),
            (ids_schema["$id"], Resource.from_contents(ids_schema)),
        )
    )
    validator = Draft202012Validator(
        permission_schema,
        registry=registry,
        format_checker=FormatChecker(),
    )

    assert list(validator.iter_errors(envelope["payload"])) == []
    assert "accountId" not in envelope["payload"]
    assert envelope["eventType"] == "PermissionChanged"
    assert envelope["schemaVersion"] == "1.0.0"
    assert session.parameters["event_type"] == "event.permission.changed.v1"
    assert session.parameters["schema_version"] == "1.0.0"
