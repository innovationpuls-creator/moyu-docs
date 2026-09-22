"""doc 28 §55 — OpenAPI + reference resolution.

Check 2: every ``$ref`` in every schema and in the OpenAPI document resolves.
Check 7: ``openapi_spec_validator.validate`` passes; the document is 3.1.x;
         every ``operationId`` is unique and equals a registered Command/Query
         logicalName; the routed logical names match the plan's 12 exactly.
"""

from __future__ import annotations

from contextlib import closing
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from _contract_helpers import (
    CONTRACT_ID_BASE,
    CONTRACTS_DIR,
    ROUTED_LOGICAL_NAMES,
    check_all_refs_resolve,
    load_yaml,
    schema_files,
)
from jsonschema_path import SchemaPath
from jsonschema_path.handlers.file import BaseFilePathHandler, FileHandler
from jsonschema_path.handlers.urllib import UrllibHandler
from openapi_spec_validator import openapi_v31_spec_validator

OPENAPI_PATH = CONTRACTS_DIR / "openapi" / "client-api.yaml"


class _LocalContractHandler(BaseFilePathHandler):
    """Resolve ``https://contracts.dom.internal/...`` canonical $id refs locally.

    The contract schemas declare absolute ``https://contracts.dom.internal/...``
    ``$id`` values (doc 28 §7); their cross-references therefore use absolute
    canonical pointers. This handler maps that origin to the local ``contracts/``
    tree so validation/codegen never performs a network fetch.
    """

    allowed_schemes = ("https",)

    def __init__(self, root: Path) -> None:
        super().__init__(file_handler=FileHandler())
        self.root = root

    def _open(self, uri: str) -> Any:
        if not uri.startswith(CONTRACT_ID_BASE):
            raise ValueError(f"unexpected URI scheme/origin: {uri}")
        rel = uri[len(CONTRACT_ID_BASE) :]
        return closing(open(self.root / rel, "rb"))


class _LocalFileHandler(BaseFilePathHandler):
    """Resolve relative ``file://`` refs (FIX-1 style) to the local contracts tree.

    After FIX-1 every cross-file ``$ref`` is a relative file path. When the OpenAPI
    document is validated, those refs resolve against the document's ``file://`` base
    URI into absolute ``file://`` URIs; this handler reads them straight from disk so
    validation stays fully offline (no network, no absolute canonical URIs).
    """

    allowed_schemes = ("file",)

    def __init__(self, root: Path) -> None:
        super().__init__(file_handler=FileHandler())
        self.root = root

    def _open(self, uri: str) -> Any:
        path = Path(urlparse(uri).path)
        if not path.exists():
            raise FileNotFoundError(f"unexpected file ref: {uri}")
        return closing(open(path, "rb"))


def _load_openapi() -> dict[str, Any]:
    assert OPENAPI_PATH.exists(), f"missing {OPENAPI_PATH}"
    return load_yaml(OPENAPI_PATH)


def test_all_schema_refs_resolve() -> None:
    for path in schema_files():
        doc = load_yaml(path)
        check_all_refs_resolve(doc, path)


def test_openapi_refs_resolve() -> None:
    doc = _load_openapi()
    check_all_refs_resolve(doc, OPENAPI_PATH)


def test_openapi_validates() -> None:
    doc = _load_openapi()
    handlers = {
        "file": _LocalFileHandler(CONTRACTS_DIR),
        "http": UrllibHandler(),
        "https": _LocalContractHandler(CONTRACTS_DIR),
    }
    base_uri = OPENAPI_PATH.as_uri()
    schema_path = SchemaPath.from_dict(doc, base_uri=base_uri, handlers=handlers)
    openapi_v31_spec_validator.cls(schema_path).validate()


def test_openapi_version_is_3_1() -> None:
    doc = _load_openapi()
    assert str(doc["openapi"]).startswith("3.1"), (
        f"OpenAPI must be 3.1.x, got {doc.get('openapi')!r}"
    )


def _collect_operations() -> list[tuple[str, str, dict]]:
    doc = _load_openapi()
    ops: list[tuple[str, str, dict]] = []
    for path, item in doc["paths"].items():
        for method, op in item.items():
            if method.lower() not in ("get", "post", "put", "delete", "patch"):
                continue
            ops.append((path, method.upper(), op))
    return ops


def _resolve_param(op: dict[str, Any], doc: dict[str, Any]) -> list[dict[str, Any]]:
    resolved: list[dict[str, Any]] = []
    for p in op.get("parameters", []):
        if "$ref" in p:
            _, _, frag = p["$ref"].partition("#")
            node: Any = doc
            for seg in [s for s in frag.split("/") if s]:
                node = node[seg]
            resolved.append(node)
        else:
            resolved.append(p)
    return resolved


def test_operation_ids_unique_and_registered() -> None:
    reg = load_yaml(CONTRACTS_DIR / "registry.yaml")
    registered = {
        e["logicalName"] for e in reg["contracts"] if e["kind"] in ("Command", "Query")
    }
    ops = _collect_operations()
    op_ids = [op[2]["operationId"] for op in ops]
    assert len(op_ids) == len(set(op_ids)), f"duplicate operationId: {op_ids}"
    # Every routed operationId must be a registered Command/Query logicalName.
    assert set(op_ids) <= registered, (
        f"operationIds {set(op_ids)} not all in registered names {registered}"
    )
    # The routed set is exactly the plan's 12 (GetAccountStatus is registered but
    # intentionally has no HTTP route this phase).
    assert set(op_ids) == ROUTED_LOGICAL_NAMES, (
        f"routed operationIds {set(op_ids)} != {ROUTED_LOGICAL_NAMES}"
    )


def test_routed_names_match_plan() -> None:
    ops = _collect_operations()
    routed = {op[2]["operationId"] for op in ops}
    assert routed == ROUTED_LOGICAL_NAMES, (
        f"routed names {routed} != plan's 12 {ROUTED_LOGICAL_NAMES}"
    )


def test_get_account_status_has_no_route() -> None:
    ops = _collect_operations()
    routed = {op[2]["operationId"] for op in ops}
    assert "GetAccountStatus" not in routed, (
        "GetAccountStatus must NOT have an HTTP route in this phase"
    )


def test_idempotency_header_only_on_required_commands() -> None:
    required = {
        "RegisterWithEmail",
        "LoginWithPassword",
        "RequestAccountDeletion",
    }
    doc = _load_openapi()
    ops = _collect_operations()
    for _path, _method, op in ops:
        oid = op["operationId"]
        has_header = any(
            p.get("name") == "Idempotency-Key" for p in _resolve_param(op, doc)
        )
        assert has_header == (oid in required), (
            f"{oid}: Idempotency-Key header presence {has_header} "
            f"!= idempotencyRequirement==required ({oid in required})"
        )


def test_set_cookie_header_on_session_establishing_commands() -> None:
    with_cookie = {"RegisterWithEmail", "LoginWithPassword"}
    ops = _collect_operations()
    for _path, _method, op in ops:
        oid = op["operationId"]
        responses = op.get("responses", {})
        has_cookie = any(
            "Set-Cookie" in (r.get("headers", {}))
            for r in responses.values()
            if isinstance(r, dict)
        )
        assert has_cookie == (oid in with_cookie), (
            f"{oid}: Set-Cookie header presence {has_cookie} "
            f"!= session-establishing ({oid in with_cookie})"
        )
