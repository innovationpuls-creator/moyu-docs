"""doc 28 §55 — registry integrity checks.

Check 3: no two registry entries share ``logicalName``.
Check 4: no two Event entries share ``eventSubject``; each matches the
         doc 28 §25 subject pattern.
Check 5: errorCode uniqueness & reachability against ``error-codes.yaml``.
Check 6: registry <-> schema bidirectional coverage and vocabulary validity.
"""

from __future__ import annotations

import re

from _contract_helpers import (
    ALLOWED_KINDS,
    ALLOWED_STATUSES,
    CANONICAL_CATEGORIES,
    CONTRACTS_DIR,
    EVENT_SUBJECT_RE,
    REPO_ROOT,
    build_id_index,
    load_yaml,
    resolve_ref,
    schema_files,
)

REGISTRY_PATH = CONTRACTS_DIR / "registry.yaml"
ERROR_CODES_PATH = CONTRACTS_DIR / "errors" / "error-codes.yaml"

EVENT_SUBJECT_PATTERN = re.compile(EVENT_SUBJECT_RE)


def _registry() -> dict:
    assert REGISTRY_PATH.exists(), f"missing {REGISTRY_PATH}"
    return load_yaml(REGISTRY_PATH)


def _error_codes() -> dict:
    assert ERROR_CODES_PATH.exists(), f"missing {ERROR_CODES_PATH}"
    return load_yaml(ERROR_CODES_PATH)


def test_no_duplicate_logical_name() -> None:
    reg = _registry()
    entries = reg["contracts"]
    names = [e["logicalName"] for e in entries]
    assert len(names) == len(set(names)), f"duplicate logicalName: {names}"


def test_event_subject_uniqueness_and_shape() -> None:
    reg = _registry()
    subjects: list[str] = []
    for entry in reg["contracts"]:
        if entry.get("kind") == "Event":
            subject = entry["eventSubject"]
            subjects.append(subject)
            assert EVENT_SUBJECT_PATTERN.match(subject), (
                f"eventSubject {subject!r} violates doc 28 §25 pattern"
            )
    assert len(subjects) == len(set(subjects)), f"duplicate eventSubject: {subjects}"


def test_error_codes_catalog_shape() -> None:
    codes = _error_codes()
    assert isinstance(codes.get("version"), str) and codes["version"], "missing version"
    assert isinstance(codes.get("codes"), dict) and codes["codes"], "missing codes"
    for code, body in codes["codes"].items():
        assert body["category"] in CANONICAL_CATEGORIES, (
            f"{code}: category {body['category']!r} not one of the 10 canonical"
        )
        assert isinstance(body.get("messageKey"), str) and body["messageKey"], (
            f"{code}: empty messageKey"
        )
        assert isinstance(body.get("retryable"), bool), f"{code}: retryable not bool"
        assert isinstance(body.get("description"), str) and body["description"], (
            f"{code}: empty description"
        )


def _contract_error_codes() -> dict[str, set[str]]:
    reg = _registry()
    mapping: dict[str, set[str]] = {}
    for entry in reg["contracts"]:
        ec = entry.get("errorCodes") or []
        mapping[entry["logicalName"]] = set(ec)
    return mapping


def test_every_referenced_error_code_exists() -> None:
    codes = set(_error_codes()["codes"].keys())
    for name, ecset in _contract_error_codes().items():
        for code in ecset:
            assert code in codes, f"{name}: references unknown errorCode {code!r}"


def test_no_contract_lists_same_code_twice() -> None:
    for name, ecset in _contract_error_codes().items():
        entry = next(e for e in _registry()["contracts"] if e["logicalName"] == name)
        listed = entry.get("errorCodes") or []
        assert len(listed) == len(ecset), f"{name}: duplicate code within errorCodes"


def test_every_catalog_code_is_reachable() -> None:
    reachable: set[str] = set()
    for ecset in _contract_error_codes().values():
        reachable |= ecset
    for code in _error_codes()["codes"].keys():
        assert code in reachable, (
            f"catalog code {code!r} is not referenced by any contract"
        )


def test_registry_schema_bidirectional_coverage() -> None:
    reg = _registry()
    registered_paths = {e["schemaPath"] for e in reg["contracts"]}
    on_disk = {str(p.relative_to(CONTRACTS_DIR.parent)) for p in schema_files()}
    # schemaPath values are stored relative to repo root (e.g. contracts/...).
    for entry in reg["contracts"]:
        sp = entry["schemaPath"]
        assert (CONTRACTS_DIR.parent / sp).exists(), f"schemaPath missing on disk: {sp}"
    # Every *.schema.json under contracts/ is registered.
    for rel in on_disk:
        assert rel in registered_paths, f"{rel} is on disk but not registered"


def test_registry_entry_vocabulary() -> None:
    reg = _registry()
    for entry in reg["contracts"]:
        assert entry["kind"] in ALLOWED_KINDS, f"{entry['logicalName']}: bad kind"
        assert entry["status"] in ALLOWED_STATUSES, (
            f"{entry['logicalName']}: bad status"
        )
        assert isinstance(entry.get("ownerDocument"), str) and entry["ownerDocument"], (
            f"{entry['logicalName']}: empty ownerDocument"
        )
        assert isinstance(entry.get("ownerModule"), str) and entry["ownerModule"], (
            f"{entry['logicalName']}: empty ownerModule"
        )
        assert isinstance(entry.get("domain"), str) and entry["domain"], (
            f"{entry['logicalName']}: empty domain"
        )
        assert isinstance(entry.get("version"), str) and entry["version"], (
            f"{entry['logicalName']}: empty version"
        )


def test_command_query_request_response_pointers() -> None:
    reg = _registry()
    id_index = build_id_index()
    for entry in reg["contracts"]:
        if entry["kind"] not in ("Command", "Query"):
            assert "eventSubject" not in entry or entry["kind"] == "Event"
            if entry["kind"] == "Event":
                continue
            # Error / Identity carry neither request/response pointers.
            assert "requestRef" not in entry and "responseRef" not in entry, (
                f"{entry['logicalName']}: unexpected request/response pointers"
            )
            continue
        req_ref = entry["requestRef"]
        resp_ref = entry["responseRef"]
        # requestRef/responseRef are stored relative to the repo root
        # (same as schemaPath), so resolve them against the repo root.
        base_file = REPO_ROOT / "registry.yaml"
        # request pointer resolves (root of the schema file).
        req_doc = resolve_ref(req_ref, base_file, id_index)
        assert isinstance(req_doc, dict), (
            f"{entry['logicalName']}: requestRef unresolved"
        )
        # response pointer resolves and its target title equals <LogicalName>Response.
        resp_doc = resolve_ref(resp_ref, base_file, id_index)
        expected_title = f"{entry['logicalName']}Response"
        assert isinstance(resp_doc, dict), (
            f"{entry['logicalName']}: responseRef unresolved"
        )
        assert resp_doc.get("title") == expected_title, (
            f"{entry['logicalName']}: response target title is "
            f"{resp_doc.get('title')!r}, expected {expected_title!r}"
        )


# FIX-6: auth contracts must not invent doc-07 resource/workspace Capability
# vocabulary; instead they declare permissionCapability=none (Auth-boundary op) and an
# authRequirement drawn from the three-value vocabulary.
AUTH_REQUIREMENT_VALUES = frozenset({"Public", "Authenticated", "RecentAuthentication"})
NON_AUTH_KINDS = frozenset({"Error", "Identity"})


def test_auth_contracts_use_permission_none_and_valid_auth_requirement() -> None:
    reg = _registry()
    for entry in reg["contracts"]:
        if entry["kind"] in NON_AUTH_KINDS:
            # Error / Identity are not auth-boundary ops; the rule does not apply.
            continue
        assert entry.get("permissionCapability") == "none", (
            f"{entry['logicalName']}: permissionCapability must be 'none' for an "
            f"auth contract, got {entry.get('permissionCapability')!r}"
        )
        assert entry.get("authRequirement") in AUTH_REQUIREMENT_VALUES, (
            f"{entry['logicalName']}: authRequirement must be one of "
            f"{sorted(AUTH_REQUIREMENT_VALUES)}, got {entry.get('authRequirement')!r}"
        )
