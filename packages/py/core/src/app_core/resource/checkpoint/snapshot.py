"""Checkpoint snapshot contract (arch 02 §nodes/06): the materialized state is
{"text": str, "nodes": list|null}; the editor's content-node tree (editor-core
kinds) rides inside the JSONB snapshot next to the body text."""

from __future__ import annotations

from typing import Any


class SnapshotError(ValueError):
    pass


_KNOWN_NODE_KINDS = {"text", "paragraph", "heading", "list"}


def validate_nodes(nodes: Any, path: str = "$") -> None:
    if nodes is None:
        return
    if not isinstance(nodes, list):
        raise SnapshotError(f"{path}: nodes must be a list")
    for i, node in enumerate(nodes):
        child_path = f"{path}[{i}]"
        if not isinstance(node, dict):
            raise SnapshotError(f"{child_path}: node must be an object")
        kind = node.get("kind")
        if kind not in _KNOWN_NODE_KINDS:
            raise SnapshotError(f"{child_path}: unknown kind {kind!r}")


def build_snapshot(text: str, nodes: list[dict[str, Any]] | None) -> dict[str, Any]:
    if not isinstance(text, str):
        raise SnapshotError("snapshot text must be a string")
    validate_nodes(nodes)
    snapshot: dict[str, Any] = {"text": text}
    if nodes is not None:
        snapshot["nodes"] = nodes
    return snapshot


def nodes_of(snapshot: dict[str, Any]) -> list[dict[str, Any]] | None:
    nodes = snapshot.get("nodes")
    validate_nodes(nodes)
    return nodes if nodes is not None else None
