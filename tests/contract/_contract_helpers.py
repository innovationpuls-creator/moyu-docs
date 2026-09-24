"""Shared helpers for contract CI tests (doc 28 §55).

Located in ``tests/contract/`` (no ``__init__.py``); imported by sibling test
modules under pytest's prepend import mode.

The helper resolves every ``$ref`` used across the contract tree, including:

* intra-document ``#/$defs/...`` pointers,
* relative file pointers such as ``../commands/auth/x.schema.json#/$defs/Y``,
* absolute canonical pointers such as
  ``https://contracts.dom.internal/ids/ids.schema.json#/$defs/UserId``
  (the canonical ID registry declared in doc 28 §9).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
CONTRACTS_DIR = REPO_ROOT / "contracts"

JSON_SCHEMA_2020_12 = "https://json-schema.org/draft/2020-12/schema"

# doc 04 §23 / Constitution §3.19 — the ten canonical top-level error categories.
CANONICAL_CATEGORIES: frozenset[str] = frozenset(
    {
        "Validation",
        "Authentication",
        "Permission",
        "NotFound",
        "Conflict",
        "RateLimit",
        "Timeout",
        "DependencyFailure",
        "Unavailable",
        "Internal",
    }
)

ALLOWED_KINDS: frozenset[str] = frozenset(
    {"Command", "Query", "Event", "Error", "Identity"}
)

ALLOWED_STATUSES: frozenset[str] = frozenset({"active", "deprecated", "removed"})

EVENT_SUBJECT_RE = r"^event\.[a-z0-9-]+\.[a-z0-9-]+\.v\d+$"

SENSITIVE_MARKER = "x-sensitive"

CONTRACT_ID_BASE = "https://contracts.dom.internal/"
ROUTED_LOGICAL_NAMES: frozenset[str] = frozenset(
    {
        "RegisterWithEmail",
        "VerifyEmail",
        "ResendEmailVerification",
        "LoginWithPassword",
        "Logout",
        "GetCurrentAccount",
        "GetCurrentSession",
        "GetAccountStatus",
        "RequestPasswordReset",
        "ResetPassword",
        "Reauthenticate",
        "RequestAccountDeletion",
        "CancelAccountDeletion",
        "CreateWorkspace",
        "ListWorkspaces",
        "GetWorkspace",
        "RenameWorkspace",
        "CreateProject",
        "ListProjects",
        "GetProjectTree",
        "ListFolderChildren",
        "RenameProject",
        "ArchiveProject",
        "UnarchiveProject",
        "TrashProject",
        "RestoreProject",
        "CreateFolder",
        "RenameFolder",
        "MoveFolder",
        "TrashFolder",
        "RestoreFolder",
        "TransferWorkspaceOwner",
        "HasSoleWorkspaceOwnership",
        "OpenResource",
        "CreateResource",
        "AppendJournalOp",
        "RenameResource",
        "TrashResource",
        "RestoreResource",
        "ListResources",
        "AddComment",
        "ListComments",
        "SearchWorkspace",
        "SearchSuggestions",
        "SearchComments",
        "SuggestMembers",
        "GetPublicNotifications",
        "GetPublicResources",
        "RotateApiKey",
        "RemoveWebhook",
        "RequeueWebhookDeliveries",
        "TestWebhook",
        "ListWebhooks",
        "RegisterWebhook",
        "ExportResource",
        "ImportResource",
        "EditComment",
        "DeleteComment",
        "CreateNamedVersion",
        "ListVersions",
        "RestoreVersion",
        "ListNotifications",
        "MarkNotificationsRead",
        "MarkNotificationRead",
        "SearchHistory",
        "ClearSearchHistory",
    }
)

# registry requestBody: none —— 客户端不发请求体，OpenAPI 不声明 requestBody，
# Canonical Schema 以 Response 为 root（doc 28 §8）
NO_BODY_LOGICAL_NAMES: frozenset[str] = frozenset(
    {
        "Logout",
        "RequestAccountDeletion",
        "CancelAccountDeletion",
        "GetCurrentAccount",
        "GetCurrentSession",
        "GetAccountStatus",
        "ListWorkspaces",
        "GetWorkspace",
        "ListProjects",
        "GetProjectTree",
        "ListFolderChildren",
        "HasSoleWorkspaceOwnership",
        "OpenResource",
        "ListResources",
        "ListComments",
        "SearchWorkspace",
        "SearchSuggestions",
        "SearchHistory",
        "ClearSearchHistory",
        "SearchComments",
        "SuggestMembers",
        "GetPublicNotifications",
        "GetPublicResources",
        "ListWebhooks",
        "RemoveWebhook",
        "TestWebhook",
        "ExportResource",
        "DeleteComment",
        "ListVersions",
        "ListNotifications",
        "MarkNotificationsRead",
        "MarkNotificationRead",
    }
)


def load_yaml(path: Path) -> dict[str, Any]:
    # `.schema.json` files are JSON (biome formats JSON with tabs, which is invalid
    # YAML), so parse them with the json module; everything else is YAML.
    text = path.read_text(encoding="utf-8")
    if path.suffix == ".json":
        data: Any = json.loads(text)
    else:
        data = yaml.safe_load(text)
    if not isinstance(data, dict):
        raise TypeError(f"{path} did not parse to a mapping")
    return data


def schema_files() -> list[Path]:
    if not CONTRACTS_DIR.exists():
        return []
    return sorted(CONTRACTS_DIR.rglob("*.schema.json"))


def build_id_index() -> dict[str, Path]:
    """Map every schema ``$id`` to its on-disk path (canonical identity, doc 28 §10)."""
    index: dict[str, Path] = {}
    for path in schema_files():
        doc = load_yaml(path)
        sid = doc.get("$id")
        if isinstance(sid, str):
            index[sid] = path
    return index


def _navigate(doc: Any, pointer: str) -> Any:
    if not pointer or pointer == "#":
        return doc
    assert pointer.startswith("#"), f"unsupported ref pointer: {pointer!r}"
    parts = [p for p in pointer[1:].split("/") if p != ""]
    current: Any = doc
    for part in parts:
        decoded = part.replace("~1", "/").replace("~0", "~")
        if isinstance(current, dict) and decoded in current:
            current = current[decoded]
        else:
            raise KeyError(f"pointer segment {decoded!r} not found in {pointer!r}")
    return current


def resolve_ref(
    ref: str,
    base_file: Path,
    id_index: dict[str, Path],
    *,
    _seen: frozenset[str] | None = None,
) -> Any:
    """Resolve a ``$ref`` string to the referenced schema object.

    Cross-file references are relative file paths so that every toolchain
    (Ajv, datamodel-codegen, openapi-typescript) resolves them offline.
    """
    seen = _seen if _seen is not None else frozenset()
    if ref in seen:
        raise RecursionError(f"ref cycle: {ref}")
    if "://" in ref:
        raise ValueError(
            f"absolute-URI $ref is not allowed (breaks offline resolvers): {ref!r}"
        )
    base_uri, _, frag = ref.partition("#")
    if base_uri == "":
        target_doc = load_yaml(base_file)
    else:
        target_path = (base_file.parent / base_uri).resolve()
        if not target_path.is_file():
            raise FileNotFoundError(
                f"ref target does not exist: {ref!r} -> {target_path}"
            )
        target_doc = load_yaml(target_path)
    return _navigate(target_doc, "#" + frag if frag else "#")


def collect_refs(node: Any) -> list[str]:
    """Recursively collect every ``$ref`` string in a document tree."""
    refs: list[str] = []
    if isinstance(node, dict):
        for key, value in node.items():
            if key == "$ref" and isinstance(value, str):
                refs.append(value)
            else:
                refs.extend(collect_refs(value))
    elif isinstance(node, list):
        for item in node:
            refs.extend(collect_refs(item))
    return refs


def check_all_refs_resolve(doc: dict[str, Any], base_file: Path) -> None:
    id_index = build_id_index()
    for ref in collect_refs(doc):
        resolve_ref(ref, base_file, id_index)


def error_envelope_path() -> Path:
    return CONTRACTS_DIR / "errors" / "error-envelope.schema.json"


def has_sensitive_field(name: str) -> bool:
    lowered = name.lower()
    return (
        lowered == "password"
        or lowered.endswith("password")
        or lowered == "token"
        or lowered.endswith("token")
        or lowered == "secret"
        or "secret" in lowered
    )
