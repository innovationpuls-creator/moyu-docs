"""doc 28 §55 — OpenAPI 面与引用解析。

Check 2: 每个 schema 与 OpenAPI 文档中的 ``$ref`` 都能解析（跨文件引用一律相对路径）。
Check 6: ``openapi_spec_validator`` 校验通过；文档为 3.1.x；``operationId`` 唯一且等于
         已注册的 Command / Query logicalName；路由集合与注册集合一致。
路由集合由 registry 决定，不由本文档决定（doc 28 §2.1）：每个 Command / Query 都有
HTTP Route，其中 requestBody: none 的操作不声明 requestBody。
"""

from __future__ import annotations

from contextlib import closing
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from _contract_helpers import (
    CONTRACTS_DIR,
    NO_BODY_LOGICAL_NAMES,
    ROUTED_LOGICAL_NAMES,
    check_all_refs_resolve,
    load_yaml,
    schema_files,
)
from jsonschema_path import SchemaPath
from jsonschema_path.handlers.file import BaseFilePathHandler, FileHandler
from openapi_spec_validator import openapi_v31_spec_validator

OPENAPI_PATH = CONTRACTS_DIR / "openapi" / "client-api.yaml"


class _LocalFileHandler(BaseFilePathHandler):
    """把相对 ``$ref`` 解析成绝对 ``file://`` URI 后直接从磁盘读取，全程离线。"""

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


def _collect_operations() -> list[tuple[str, str, dict]]:
    doc = _load_openapi()
    ops: list[tuple[str, str, dict]] = []
    for path, item in doc["paths"].items():
        for method, op in item.items():
            if method.lower() not in ("get", "post", "put", "delete", "patch"):
                continue
            ops.append((path, method.upper(), op))
    return ops


def _routed_names() -> set[str]:
    return {op[2]["operationId"] for op in _collect_operations()}


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


def test_all_schema_refs_resolve() -> None:
    for path in schema_files():
        doc = load_yaml(path)
        check_all_refs_resolve(doc, path)


def test_openapi_refs_resolve() -> None:
    doc = _load_openapi()
    check_all_refs_resolve(doc, OPENAPI_PATH)


def test_no_absolute_uri_refs() -> None:
    """跨文件引用必须是相对路径：绝对 URI 会让离线解析器改走网络。"""
    offenders: list[str] = []
    for path in [*schema_files(), OPENAPI_PATH]:
        for ref in _collect_refs(load_yaml(path)):
            if "://" in ref:
                offenders.append(f"{path.relative_to(CONTRACTS_DIR)}: {ref}")
    assert not offenders, f"absolute-URI $ref found: {offenders}"


def _collect_refs(node: Any) -> list[str]:
    refs: list[str] = []
    if isinstance(node, dict):
        for key, value in node.items():
            if key == "$ref" and isinstance(value, str):
                refs.append(value)
            else:
                refs.extend(_collect_refs(value))
    elif isinstance(node, list):
        for item in node:
            refs.extend(_collect_refs(item))
    return refs


def test_openapi_validates() -> None:
    doc = _load_openapi()
    handlers = {"file": _LocalFileHandler(CONTRACTS_DIR)}
    schema_path = SchemaPath.from_dict(
        doc, base_uri=OPENAPI_PATH.as_uri(), handlers=handlers
    )
    openapi_v31_spec_validator.cls(schema_path).validate()


def test_openapi_version_is_3_1() -> None:
    doc = _load_openapi()
    assert str(doc["openapi"]).startswith("3.1"), (
        f"OpenAPI must be 3.1.x, got {doc.get('openapi')!r}"
    )


def test_operation_ids_unique_and_registered() -> None:
    reg = load_yaml(CONTRACTS_DIR / "registry.yaml")
    registered = {
        e["logicalName"] for e in reg["contracts"] if e["kind"] in ("Command", "Query")
    }
    op_ids = [op[2]["operationId"] for op in _collect_operations()]
    assert len(op_ids) == len(set(op_ids)), f"duplicate operationId: {op_ids}"
    assert set(op_ids) <= registered, (
        f"operationIds {set(op_ids)} not all in registered names {registered}"
    )


def test_every_command_and_query_is_routed() -> None:
    """注册即路由：registered(Command|Query) == routed operationId 集合。"""
    reg = load_yaml(CONTRACTS_DIR / "registry.yaml")
    registered = {
        e["logicalName"] for e in reg["contracts"] if e["kind"] in ("Command", "Query")
    }
    routed = _routed_names()
    assert routed == registered, (
        f"routed {sorted(routed)} != registered Command/Query {sorted(registered)}"
    )
    assert routed == ROUTED_LOGICAL_NAMES, (
        f"routed names {sorted(routed)} != expected {sorted(ROUTED_LOGICAL_NAMES)}"
    )


def test_get_account_status_is_a_routed_client_query() -> None:
    doc = _load_openapi()
    status_path = doc["paths"]["/v1/auth/status"]
    assert status_path["get"]["operationId"] == "GetAccountStatus"
    schema = status_path["get"]["responses"]["200"]["content"]["application/json"][
        "schema"
    ]
    assert schema["$ref"] == "../queries/auth/get-account-status.schema.json"


def test_no_body_operations_declare_no_request_body() -> None:
    """no-body 操作不得要求客户端发送占位空对象（doc 28 §8）。"""
    for _path, _method, op in _collect_operations():
        oid = op["operationId"]
        has_body = "requestBody" in op
        assert has_body == (oid not in NO_BODY_LOGICAL_NAMES), (
            f"{oid}: requestBody presence {has_body} != "
            f"no-body ({oid in NO_BODY_LOGICAL_NAMES})"
        )


def test_idempotency_header_only_on_required_commands() -> None:
    reg = load_yaml(CONTRACTS_DIR / "registry.yaml")
    required = {
        e["logicalName"]
        for e in reg["contracts"]
        if e.get("idempotencyRequirement") == "required"
    }
    assert required == {
        "RegisterWithEmail",
        "LoginWithPassword",
        "RequestAccountDeletion",
        "CreateWorkspace",
        "RenameWorkspace",
        "CreateProject",
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
        "CreateResource",
        "AppendJournalOp",
        "RenameResource",
        "TrashResource",
        "RestoreResource",
        "AddComment",
        "ImportResource",
        "EditComment",
        "DeleteComment",
        "CreateNamedVersion",
        "CreateVersionRestoreTask",
        "RetryTask",
        "CreateResourceExportTask",
        "CreateResourceShareLink",
        "CreateWorkspaceInvitation",
        "RegenerateResourceShareLink",
        "RemoveProjectMember",
        "RemoveResourcePermission",
        "RemoveWorkspaceMember",
        "RevokeResourceShareLink",
        "RevokeWorkspaceInvitation",
        "SetProjectMemberRole",
        "SetResourcePermission",
        "SetResourceShareLinkExpiry",
        "UploadAsset",
    }, f"unexpected idempotencyRequirement==required set: {required}"
    doc = _load_openapi()
    for _path, _method, op in _collect_operations():
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
    for _path, _method, op in _collect_operations():
        oid = op["operationId"]
        has_cookie = any(
            "Set-Cookie" in r.get("headers", {})
            for r in op.get("responses", {}).values()
            if isinstance(r, dict)
        )
        assert has_cookie == (oid in with_cookie), (
            f"{oid}: Set-Cookie header presence {has_cookie} "
            f"!= session-establishing ({oid in with_cookie})"
        )
