#!/usr/bin/env python3
"""契约 Breaking Change Detection（docs/architecture/28 §49-§51、§55.1）。

基线是 `contracts/registry-baseline.json`，保存每条注册 Contract 的结构指纹：
kind、eventSubject、version major，以及其 Canonical Schema 中每个字段节点的
type / required / enum / $ref。

```text
--check            与基线比对；出现 §50 的 Breaking 变化即失败
--update-baseline  显式重建基线（必须表现为一次可见的提交差异）
```

Breaking（§50）：删除字段、字段含义/类型变更、optional→required、enum 成员被删除、
kind 或 eventSubject 变更、version major 降低、Contract 从注册表移除。
Non-breaking（§49）：新增可选字段、新增 Contract、新增 enum 成员、required→optional。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
REGISTRY = REPO_ROOT / "contracts" / "registry.yaml"
BASELINE = REPO_ROOT / "contracts" / "registry-baseline.json"
BASELINE_VERSION = "1.0.0"

SHAPE_KEYS = ("type", "required", "enum", "ref")


def _registry() -> list[dict]:
    data = yaml.safe_load(REGISTRY.read_text(encoding="utf-8"))
    return data["contracts"]


def _node_entry(node: dict) -> dict[str, Any]:
    """取一个 schema 节点上参与契约判定的键。"""
    entry: dict[str, Any] = {}
    if "$ref" in node:
        entry["ref"] = node["$ref"]
    if "type" in node:
        entry["type"] = node["type"]
    if "enum" in node:
        entry["enum"] = node["enum"]
    return entry


def fingerprint_schema(schema: dict) -> dict[str, dict[str, Any]]:
    """把一个 JSON Schema 折算成 {节点指针: {type|required|enum|ref}}。"""
    shape: dict[str, dict[str, Any]] = {}

    def walk(node: Any, pointer: str) -> None:
        if not isinstance(node, dict):
            return
        entry = _node_entry(node)
        if entry:
            shape[pointer] = entry
        required = set(node.get("required") or [])
        for name, sub in (node.get("properties") or {}).items():
            child = f"{pointer}/properties/{name}"
            walk(sub, child)
            if name in required:
                shape.setdefault(child, {})["required"] = True
        for name, sub in (node.get("$defs") or {}).items():
            walk(sub, f"{pointer}/$defs/{name}")
        if isinstance(node.get("items"), dict):
            walk(node["items"], f"{pointer}/items")

    walk(schema, "#")
    return shape


def fingerprint_registry() -> dict[str, dict[str, Any]]:
    contracts: dict[str, dict[str, Any]] = {}
    for entry in _registry():
        name = entry["logicalName"]
        schema_path = REPO_ROOT / entry["schemaPath"]
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
        contracts[name] = {
            "kind": entry["kind"],
            "eventSubject": entry.get("eventSubject"),
            "versionMajor": int(str(entry["version"]).split(".")[0]),
            "shape": fingerprint_schema(schema),
        }
    return contracts


def build_baseline() -> dict[str, Any]:
    return {
        "version": BASELINE_VERSION,
        "source": "contracts/registry.yaml",
        "contracts": fingerprint_registry(),
    }


def compare(
    current: dict[str, Any], baseline: dict[str, Any]
) -> tuple[list[str], list[str]]:
    """返回 (breaking, non_breaking) 两类问题描述。"""
    breaking: list[str] = []
    non_breaking: list[str] = []
    base_contracts = baseline.get("contracts", {})
    for name, before in base_contracts.items():
        after = current.get(name)
        if after is None:
            breaking.append(f"{name}: Contract 从注册表移除")
            continue
        if before.get("kind") != after.get("kind"):
            breaking.append(
                f"{name}: kind 由 {before.get('kind')} 变为 {after.get('kind')}"
            )
        if before.get("eventSubject") and before["eventSubject"] != after.get(
            "eventSubject"
        ):
            breaking.append(f"{name}: eventSubject 由 {before['eventSubject']} 变更")
        if after.get("versionMajor", 0) < before.get("versionMajor", 0):
            breaking.append(f"{name}: version major 降低")
        # A contract with a higher major version is a new compatibility
        # surface. Its changed fields are allowed to differ from old clients;
        # kind and event subject changes remain independently checked above.
        if after.get("versionMajor", 0) == before.get("versionMajor", 0):
            breaking.extend(
                _compare_shape(name, before.get("shape", {}), after.get("shape", {}))
            )
        non_breaking.extend(
            _added_nodes(name, before.get("shape", {}), after.get("shape", {}))
        )
    for name in sorted(set(current) - set(base_contracts)):
        non_breaking.append(f"{name}: 新增 Contract（需更新基线）")
    return breaking, non_breaking


def _compare_shape(
    name: str, before: dict[str, Any], after: dict[str, Any]
) -> list[str]:
    problems: list[str] = []
    for pointer, old in before.items():
        new = after.get(pointer)
        if new is None:
            problems.append(f"{name}: 删除字段 {pointer}")
            continue
        if old.get("type") != new.get("type"):
            problems.append(
                f"{name}: {pointer} type 由 {old.get('type')} 变为 {new.get('type')}"
            )
        if old.get("ref") != new.get("ref"):
            problems.append(f"{name}: {pointer} $ref 目标变更")
        old_enum, new_enum = old.get("enum"), new.get("enum")
        if old_enum is not None and new_enum is not None:
            removed = [v for v in old_enum if v not in new_enum]
            if removed:
                problems.append(f"{name}: {pointer} enum 成员被删除 {removed}")
        elif old_enum is not None and new_enum is None:
            problems.append(f"{name}: {pointer} 取消了 enum 约束")
        if not old.get("required") and new.get("required"):
            problems.append(f"{name}: {pointer} optional -> required")
    return problems


def _added_nodes(name: str, before: dict[str, Any], after: dict[str, Any]) -> list[str]:
    added = sorted(set(after) - set(before))
    if added:
        return [f"{name}: 新增字段节点 {added}（需更新基线）"]
    return []


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="契约 Breaking Change Detection")
    parser.add_argument("--update-baseline", action="store_true", help="重建基线")
    args = parser.parse_args(argv)

    if args.update_baseline:
        BASELINE.write_text(
            json.dumps(build_baseline(), indent="\t", ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        print(f"PASS：已重建基线 {BASELINE.relative_to(REPO_ROOT)}")
        return 0

    if not BASELINE.is_file():
        print(f"FAIL：缺少基线文件 {BASELINE}（执行 --update-baseline 建立）")
        return 1

    baseline = json.loads(BASELINE.read_text(encoding="utf-8"))
    breaking, non_breaking = compare(fingerprint_registry(), baseline)

    for item in non_breaking:
        print(f"  info: {item}")
    if breaking:
        print("FAIL：检测到 Breaking Contract Change（docs/architecture/28 §50）")
        for item in breaking:
            print(f"  - {item}")
        return 1
    print("PASS：无 Breaking Contract Change")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
