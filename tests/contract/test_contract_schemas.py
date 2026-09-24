"""doc 28 §55 — Phase 9 Task 27: schema-facing contract checks.

Focus (the registry is the generation root, doc 28 §2.1):

- every contract schemaPath registered in registry.yaml is a valid JSON Schema
  2020-12 document with the canonical ``$schema``/``$id``,
- every ``$ref`` inside those schemas resolves within the on-disk file set
  (offline toolchain guarantee, doc 28 §10),
- errorCode catalog hygiene: SCREAMING_SNAKE pattern (envelope schema pattern
  ``^[A-Z0-9_]+$``), unique codes, unique messageKeys (client localization
  collision guard), and reachability — every catalog code is referenced by at
  least one registered contract OR is a documented envelope-level code,
- OpenAPI 3.1 validity of contracts/openapi/client-api.yaml,
- Phase 7/8 surfaced business codes stay registered with correct
  category/messageKey (task-11 Part B regression guard).

logicalName uniqueness and eventSubject uniqueness are asserted in
test_contract_registry.py (Check 3 / Check 4) and are not duplicated here.
"""

from __future__ import annotations

import re

from _contract_helpers import (
    CONTRACTS_DIR,
    JSON_SCHEMA_2020_12,
    REPO_ROOT,
    check_all_refs_resolve,
    load_yaml,
)
from jsonschema import Draft202012Validator

REGISTRY_PATH = CONTRACTS_DIR / "registry.yaml"
ERROR_CODES_PATH = CONTRACTS_DIR / "errors" / "error-codes.yaml"
OPENAPI_PATH = CONTRACTS_DIR / "openapi" / "client-api.yaml"

CODE_PATTERN = re.compile(r"^[A-Z0-9_]+$")

# Envelope-level codes emitted by the API error handler for HTTP / validation /
# infrastructure failures. They are documented here (doc 28 §28) and
# intentionally NOT tied to a single business contract, so the reachability
# rule accepts them as "documented envelope codes".
DOCUMENTED_ENVELOPE_CODES: frozenset[str] = frozenset(
    {
        "BAD_REQUEST",
        "UNAUTHENTICATED",
        "FORBIDDEN",
        "NOT_FOUND",
        "METHOD_NOT_ALLOWED",
        "CONFLICT",
        "REQUEST_VALIDATION_ERROR",
        "INTERNAL_ERROR",
    }
)

# Business codes surfaced by the Phase 7/8 API layer that must remain in the
# canonical catalog (task-11 Part B regression guard).
WORKSPACE_SCHEMA_PATHS = {
    "CreateWorkspace": "contracts/commands/workspace/create-workspace.schema.json",
    "ListWorkspaces": "contracts/queries/workspace/list-workspaces.schema.json",
    "GetWorkspace": "contracts/queries/workspace/get-workspace.schema.json",
    "RenameWorkspace": "contracts/commands/workspace/rename-workspace.schema.json",
    "CreateProject": "contracts/commands/workspace/create-project.schema.json",
    "ListProjects": "contracts/queries/workspace/list-projects.schema.json",
    "GetProjectTree": "contracts/queries/workspace/get-project-tree.schema.json",
    "ListFolderChildren": "contracts/"
    "queries/workspace/list-folder-children.schema.json",
    "RenameProject": "contracts/commands/workspace/rename-project.schema.json",
    "ArchiveProject": "contracts/commands/workspace/archive-project.schema.json",
    "UnarchiveProject": "contracts/commands/workspace/unarchive-project.schema.json",
    "TrashProject": "contracts/commands/workspace/trash-project.schema.json",
    "RestoreProject": "contracts/commands/workspace/restore-project.schema.json",
    "CreateFolder": "contracts/commands/workspace/create-folder.schema.json",
    "RenameFolder": "contracts/commands/workspace/rename-folder.schema.json",
    "MoveFolder": "contracts/commands/workspace/move-folder.schema.json",
    "TrashFolder": "contracts/commands/workspace/trash-folder.schema.json",
    "RestoreFolder": "contracts/commands/workspace/restore-folder.schema.json",
    "TransferWorkspaceOwner": "contracts/"
    "commands/permission/transfer-workspace-owner.schema.json",
    "HasSoleWorkspaceOwnership": "contracts/"
    "queries/permission/has-sole-workspace-ownership.schema.json",
}

PHASE7_SURFACED_CODES: dict[str, str] = {
    "ACCOUNT_IN_RECOVERY_MODE": "Permission",
    "ACCOUNT_NOT_FOUND": "NotFound",
    "SESSION_NOT_AUTHORIZED": "Authentication",
}


def _registry() -> dict:
    return load_yaml(REGISTRY_PATH)


def _error_codes() -> dict:
    return load_yaml(ERROR_CODES_PATH)


def _registry_schema_paths() -> list[tuple[str, object]]:
    """(logicalName, schemaPath) for every registered contract (doc 28 §2.1)."""
    return [(e["logicalName"], e["schemaPath"]) for e in _registry()["contracts"]]


def test_workspace_contract_schemas_are_registered_at_canonical_paths() -> None:
    registry = _registry()
    entries = {
        entry["logicalName"]: entry["schemaPath"]
        for entry in registry["contracts"]
        if entry.get("domain") in {"workspace", "permission"}
    }
    for name, path in WORKSPACE_SCHEMA_PATHS.items():
        assert entries.get(name) == path, f"{name}: expected registered schema {path}"
        schema = load_yaml(REPO_ROOT / path)
        assert schema.get("$schema") == JSON_SCHEMA_2020_12
        assert schema.get("$id", "").startswith("https://contracts.dom.internal/")


RESOURCE_SCHEMA_PATHS = {
    "OpenResource": "contracts/queries/resource/open-resource.schema.json",
}


def test_resource_contract_schemas_are_valid_2020_12() -> None:
    for name, schema_path in RESOURCE_SCHEMA_PATHS.items():
        path = REPO_ROOT / schema_path
        assert path.is_file(), f"{name}: missing canonical schema {schema_path}"
        Draft202012Validator.check_schema(load_yaml(path))


def test_workspace_contract_schemas_are_valid_2020_12() -> None:
    for name, schema_path in WORKSPACE_SCHEMA_PATHS.items():
        path = REPO_ROOT / schema_path
        assert path.is_file(), f"{name}: missing canonical schema {schema_path}"
        Draft202012Validator.check_schema(load_yaml(path))


def test_workspace_contract_registry_entries_keep_permission_storage_owned() -> None:
    registry = _registry()
    entries = {entry["logicalName"]: entry for entry in registry["contracts"]}
    for name in WORKSPACE_SCHEMA_PATHS:
        assert (
            entries[name]["ownerModule"] == "packages/py/core/permission"
            if name
            in {
                "TransferWorkspaceOwner",
                "HasSoleWorkspaceOwnership",
            }
            else entries[name]["ownerModule"] == "packages/py/core/workspace"
        )
    transfer = load_yaml(REPO_ROOT / WORKSPACE_SCHEMA_PATHS["TransferWorkspaceOwner"])
    assert "Permission-owned" in transfer["description"]
    assert "Project Owner rows" in transfer["description"]


def test_every_registry_schema_is_valid_2020_12() -> None:
    entries = _registry_schema_paths()
    assert entries, "registry.yaml registers no contracts"
    for name, schema_path in entries:
        path = REPO_ROOT / str(schema_path)
        assert path.is_file(), f"{name}: schemaPath missing on disk: {schema_path}"
        doc = load_yaml(path)
        assert isinstance(doc, dict), f"{name}: {schema_path} is not a mapping"
        assert doc.get("$schema") == JSON_SCHEMA_2020_12, (
            f"{name}: {schema_path} must declare $schema 2020-12"
        )
        Draft202012Validator.check_schema(doc)


def test_every_registry_schema_refs_resolve_within_file_set() -> None:
    """Every ``$ref`` in every registered schema resolves offline (doc 28 §10):
    relative cross-file paths exist and intra-document pointers navigate."""
    for name, schema_path in _registry_schema_paths():
        path = REPO_ROOT / str(schema_path)
        check_all_refs_resolve(load_yaml(path), path)


def test_error_codes_match_envelope_pattern() -> None:
    for code in _error_codes()["codes"]:
        assert CODE_PATTERN.match(code), (
            f"catalog errorCode {code!r} violates envelope pattern ^[A-Z0-9_]+$"
        )
    for entry in _registry()["contracts"]:
        for code in entry.get("errorCodes") or []:
            assert CODE_PATTERN.match(code), (
                f"{entry['logicalName']}: errorCode {code!r} violates pattern"
            )


def test_catalog_error_codes_are_unique() -> None:
    codes = list(_error_codes()["codes"])
    assert len(codes) == len(set(codes)), "duplicate errorCode in the catalog"


def test_catalog_message_keys_are_unique() -> None:
    keys = [body["messageKey"] for body in _error_codes()["codes"].values()]
    assert len(keys) == len(set(keys)), f"duplicate messageKey: {keys}"


def test_every_catalog_code_reachable_or_documented_envelope_code() -> None:
    reachable: set[str] = set()
    for entry in _registry()["contracts"]:
        reachable |= set(entry.get("errorCodes") or [])
    for code in _error_codes()["codes"]:
        assert code in reachable or code in DOCUMENTED_ENVELOPE_CODES, (
            f"catalog code {code!r} is neither referenced by a contract nor a "
            f"documented envelope code"
        )


def test_openapi_client_api_validates_as_openapi_3_1() -> None:
    """OpenAPI 3.1 validity with offline relative-``$ref`` resolution (same
    machinery as test_contract_openapi.py, doc 28 §55 Check 6/Check 2)."""
    from contextlib import closing
    from pathlib import Path
    from typing import Any
    from urllib.parse import urlparse

    from jsonschema_path import SchemaPath
    from jsonschema_path.handlers.file import BaseFilePathHandler, FileHandler
    from openapi_spec_validator import openapi_v31_spec_validator

    class _LocalFileHandler(BaseFilePathHandler):
        allowed_schemes = ("file",)

        def __init__(self, root: Path) -> None:
            super().__init__(file_handler=FileHandler())
            self.root = root

        def _open(self, uri: str) -> Any:
            path = Path(urlparse(uri).path)
            if not path.exists():
                raise FileNotFoundError(f"unexpected file ref: {uri}")
            return closing(open(path, "rb"))

    doc = load_yaml(OPENAPI_PATH)
    assert str(doc["openapi"]).startswith("3.1"), (
        f"client-api.yaml must be OpenAPI 3.1, got {doc['openapi']!r}"
    )
    schema_path = SchemaPath.from_dict(
        doc,
        base_uri=OPENAPI_PATH.as_uri(),
        handlers={"file": _LocalFileHandler(CONTRACTS_DIR)},
    )
    openapi_v31_spec_validator.cls(schema_path).validate()


def test_phase7_surfaced_codes_registered_with_metadata() -> None:
    """Phase 7/8 API-layer codes are registered with the correct canonical
    category/messageKey and reachable from at least one contract (task-11)."""
    codes = _error_codes()["codes"]
    contract_codes: set[str] = set()
    for entry in _registry()["contracts"]:
        contract_codes |= set(entry.get("errorCodes") or [])
    for code, expected_category in PHASE7_SURFACED_CODES.items():
        body = codes.get(code)
        assert body is not None, f"{code}: not registered in error-codes.yaml"
        assert body["category"] == expected_category, (
            f"{code}: category {body['category']!r}, expected {expected_category!r}"
        )
        assert isinstance(body["messageKey"], str) and body["messageKey"].startswith(
            "auth.error."
        ), f"{code}: missing messageKey"
        assert isinstance(body["retryable"], bool), f"{code}: retryable not bool"
        assert isinstance(body["description"], str) and body["description"], (
            f"{code}: empty description"
        )
        assert code in contract_codes, (
            f"{code}: registered but not referenced by any contract's errorCodes"
        )
