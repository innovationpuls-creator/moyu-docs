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
    """requestRef / responseRef / requestBody 三者必须互相自洽（doc 28 §8）。

    requestBody: required -> 请求是文件 root，响应在 $defs.<LogicalName>Response
    requestBody: none     -> requestRef 记为 none，文件 root 即响应，生成物中
                             只存在 Response 类型
    """
    reg = _registry()
    id_index = build_id_index()
    base_file = REPO_ROOT / "registry.yaml"
    for entry in reg["contracts"]:
        kind = entry["kind"]
        if kind not in ("Command", "Query"):
            if kind == "Error" or kind == "Identity":
                assert "requestRef" not in entry and "responseRef" not in entry, (
                    f"{entry['logicalName']}: unexpected request/response pointers"
                )
            continue
        name = entry["logicalName"]
        expected_title = f"{name}Response"
        assert entry.get("requestBody") in ("required", "none"), (
            f"{name}: requestBody must be required or none"
        )
        resp_doc = resolve_ref(entry["responseRef"], base_file, id_index)
        assert isinstance(resp_doc, dict), f"{name}: responseRef unresolved"
        assert resp_doc.get("title") == expected_title, (
            f"{name}: response target title is {resp_doc.get('title')!r}, "
            f"expected {expected_title!r}"
        )
        if entry["requestBody"] == "required":
            assert entry["requestRef"] != "none", (
                f"{name}: required body needs requestRef"
            )
            req_doc = resolve_ref(entry["requestRef"], base_file, id_index)
            assert isinstance(req_doc, dict), f"{name}: requestRef unresolved"
            assert req_doc.get("title") == name, (
                f"{name}: request target title is {req_doc.get('title')!r}, "
                f"expected {name!r}"
            )
            assert entry["responseRef"] != entry["schemaPath"], (
                f"{name}: a body-carrying contract cannot have its response at root"
            )
        else:
            assert entry["requestRef"] == "none", (
                f"{name}: no-body contract must record requestRef: none"
            )
            assert entry["responseRef"] == entry["schemaPath"], (
                f"{name}: no-body contract's response IS the schema root"
            )


AUTH_REQUIREMENT_VALUES = frozenset({"Public", "Authenticated", "RecentAuthentication"})
NON_AUTH_KINDS = frozenset({"Error", "Identity"})


def test_auth_contracts_use_permission_none_and_valid_auth_requirement() -> None:
    """Auth 边界操作不受 doc 07 的 Capability 管辖；边界由 authRequirement 表达。"""
    reg = _registry()
    for entry in reg["contracts"]:
        kind = entry["kind"]
        name = entry["logicalName"]
        if kind in ("Command", "Query"):
            assert entry.get("permissionCapability") == "none", (
                f"{name}: permissionCapability must be 'none', got "
                f"{entry.get('permissionCapability')!r}"
            )
            assert entry.get("authRequirement") in AUTH_REQUIREMENT_VALUES, (
                f"{name}: authRequirement must be one of "
                f"{sorted(AUTH_REQUIREMENT_VALUES)}, "
                f"got {entry.get('authRequirement')!r}"
            )
        elif kind == "Event":
            assert entry.get("permissionCapability") == "none", (
                f"{name}: permissionCapability must be 'none'"
            )
            assert "authRequirement" not in entry, (
                f"{name}: authRequirement applies to Command/Query only"
            )
        else:
            # Error / Identity 不是 Auth 边界操作，不参与该词汇。
            assert "permissionCapability" not in entry, (
                f"{name}: {kind} 不应声明 permissionCapability"
            )
            assert "authRequirement" not in entry, (
                f"{name}: {kind} 不应声明 authRequirement"
            )
