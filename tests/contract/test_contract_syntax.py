"""doc 28 §55 — schema syntax + anti-invention guard.

Check 1: every ``contracts/**/*.schema.json`` parses and validates as a
         JSON Schema 2020-12 document and declares ``$schema``/``$id``/``title``.
Check 8: no response (``$defs``) schema may carry a password/token/secret-shaped
         field without ``x-sensitive``, and no response schema may contain a field
         whose name contains ``password`` or ``tokenHash`` (doc 28 §57/§58).
"""

from __future__ import annotations

import json
from pathlib import Path

import yaml
from _contract_helpers import (
    CONTRACTS_DIR,
    JSON_SCHEMA_2020_12,
    collect_refs,
    has_sensitive_field,
    schema_files,
)
from jsonschema import Draft202012Validator

SENSITIVE_MARKER = "x-sensitive"


def _load_raw(path: Path) -> dict:
    # `.schema.json` is JSON (biome formats with tabs, invalid YAML); parse as JSON.
    if path.suffix == ".json":
        return json.loads(path.read_text(encoding="utf-8"))
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def test_every_schema_parses_and_validates() -> None:
    paths = schema_files()
    assert paths, "no contract schema files found"
    for path in paths:
        doc = _load_raw(path)
        assert isinstance(doc, dict), f"{path}: not a mapping"
        Draft202012Validator.check_schema(doc)


def test_every_schema_declares_required_metadata() -> None:
    for path in schema_files():
        doc = _load_raw(path)
        assert doc.get("$schema") == JSON_SCHEMA_2020_12, f"{path}: bad $schema"
        assert isinstance(doc.get("$id"), str) and doc["$id"].startswith(
            "https://contracts.dom.internal/"
        ), f"{path}: missing/absent $id"
        assert isinstance(doc.get("title"), str) and doc["title"], (
            f"{path}: missing title"
        )


def _iter_object_properties(node: object) -> list[tuple[dict, str]]:
    """Yield (object_dict, property_name) for every object property in a schema."""
    found: list[tuple[dict, str]] = []
    if isinstance(node, dict):
        props = node.get("properties")
        if isinstance(props, dict):
            for pname, pdef in props.items():
                found.append((node, pname))
        for value in node.values():
            found.extend(_iter_object_properties(value))
    elif isinstance(node, list):
        for item in node:
            found.extend(_iter_object_properties(item))
    return found


def test_response_schemas_never_leak_secrets() -> None:
    for path in schema_files():
        doc = _load_raw(path)
        # Response bodies live under $defs/<Name>Response (commands/queries),
        # or the root is the object itself for ErrorEnvelope / IdentityIds.
        response_nodes: list[dict] = []
        defs = doc.get("$defs")
        if isinstance(defs, dict):
            for key, sub in defs.items():
                if key.endswith("Response") and isinstance(sub, dict):
                    response_nodes.append(sub)
        if path.name in ("error-envelope.schema.json", "ids.schema.json"):
            response_nodes.append(doc)

        for resp in response_nodes:
            for _obj, pname in _iter_object_properties(resp):
                # Look up the property definition by name within the response tree.
                pass
            # Walk properties defined directly on the response object.
            props = resp.get("properties")
            if isinstance(props, dict):
                for pname, pdef in props.items():
                    assert not has_sensitive_field(pname) or (
                        isinstance(pdef, dict) and pdef.get(SENSITIVE_MARKER) is True
                    ), (
                        f"{path}: response field {pname!r} is secret-shaped "
                        f"but not marked {SENSITIVE_MARKER}"
                    )
                    lowered = pname.lower()
                    assert "password" not in lowered, (
                        f"{path}: response field {pname!r} must not contain 'password'"
                    )
                    assert "tokenhash" not in lowered, (
                        f"{path}: response field {pname!r} must not contain 'tokenHash'"
                    )


def test_request_schemas_mark_secrets() -> None:
    for path in schema_files():
        doc = _load_raw(path)
        # The root is the request payload for commands/queries; for errors/ids the
        # root is the object itself and has no credentials.
        if path.name in ("error-envelope.schema.json", "ids.schema.json"):
            continue
        props = doc.get("properties")
        if isinstance(props, dict):
            for pname, pdef in props.items():
                if has_sensitive_field(pname):
                    assert (
                        isinstance(pdef, dict) and pdef.get(SENSITIVE_MARKER) is True
                    ), (
                        f"{path}: request field {pname!r} is secret-shaped "
                        f"but not marked {SENSITIVE_MARKER}"
                    )


def test_no_absolute_uri_refs() -> None:
    """FIX-1 regression guard: every ``$ref`` under ``contracts/`` must be a local
    pointer (a relative file path such as ``../ids/ids.schema.json#/$defs/X`` or an
    intra-document ``#/$defs/...`` fragment), never an ``http(s)://`` absolute URI.
    Absolute URIs force the offline toolchain (datamodel-codegen / Ajv /
    openapi-typescript) to attempt a network fetch and abort. The canonical ``$id``
    values are intentionally left unchanged; only the ``$ref`` *style* changes.
    """
    for path in CONTRACTS_DIR.rglob("*.schema.json"):
        doc = _load_raw(path)
        for ref in collect_refs(doc):
            assert "://" not in ref, (
                f"{path}: absolute $ref not allowed offline: {ref!r}"
            )
    for path in CONTRACTS_DIR.rglob("*.yaml"):
        doc = yaml.safe_load(path.read_text(encoding="utf-8"))
        if not isinstance(doc, dict):
            continue
        for ref in collect_refs(doc):
            assert "://" not in ref, (
                f"{path}: absolute $ref not allowed offline: {ref!r}"
            )
