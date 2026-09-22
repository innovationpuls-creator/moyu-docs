"""Contract CI 义务账本与 Breaking Change Detection（docs/architecture/28 §55-§56）。

1. `contracts/contract-ci.yaml` 必须与 §55 的十项义务一一对应。
2. `not-applicable` 只允许是带触发条件的临时状态。
3. Breaking Change 检查必须真的能报出 §50 的破坏性变化。
"""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
CONTRACTS_DIR = REPO_ROOT / "contracts"
COMPAT_SCRIPT = REPO_ROOT / "scripts" / "check_contract_compat.py"
BASELINE = CONTRACTS_DIR / "registry-baseline.json"
CI_LEDGER = CONTRACTS_DIR / "contract-ci.yaml"

# docs/architecture/28 §55 列出的十项义务
DOC_28_SECTION_55 = (
    "schema-syntax-validation",
    "reference-resolution",
    "duplicate-logical-name-check",
    "duplicate-event-subject-check",
    "error-code-uniqueness",
    "openapi-validation",
    "breaking-change-detection",
    "code-generation",
    "generated-drift-check",
    "consumer-contract-tests",
)


def _load_module() -> Any:
    assert COMPAT_SCRIPT.is_file(), f"缺少 {COMPAT_SCRIPT}"
    spec = importlib.util.spec_from_file_location(
        "check_contract_compat", COMPAT_SCRIPT
    )
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load {COMPAT_SCRIPT}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _run(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(COMPAT_SCRIPT), *args],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )


def test_breaking_change_check_passes_with_current_baseline() -> None:
    result = _run()
    assert result.returncode == 0, (
        "Breaking change 检查失败 "
        f"(exit {result.returncode})\n{result.stdout}{result.stderr}"
    )


def test_baseline_covers_exactly_the_registered_contracts() -> None:
    """基线必须与注册表同步：新增 Contract 后必须显式重建基线。"""
    registry = yaml.safe_load(
        (CONTRACTS_DIR / "registry.yaml").read_text(encoding="utf-8")
    )
    registered = {entry["logicalName"] for entry in registry["contracts"]}
    baseline = json.loads(BASELINE.read_text(encoding="utf-8"))
    recorded = set(baseline["contracts"])
    assert recorded == registered, (
        f"基线与注册表不同步；执行 `python scripts/check_contract_compat.py "
        f"--update-baseline`（缺失: {sorted(registered - recorded)}, "
        f"多余: {sorted(recorded - registered)}）"
    )


def test_baseline_fingerprints_are_non_trivial() -> None:
    baseline = json.loads(BASELINE.read_text(encoding="utf-8"))
    for name, entry in baseline["contracts"].items():
        assert entry["kind"] in {"Command", "Query", "Event", "Error", "Identity"}
        assert entry["versionMajor"] >= 1
        assert entry["shape"], f"{name}: 结构指纹为空"


def test_comparator_detects_each_breaking_change_class() -> None:
    """反向守卫：§50 的每一类破坏性变化都必须被报出。"""
    module = _load_module()
    base_shape = {
        "#/properties/email": {"type": "string"},
        "#/properties/status": {"enum": ["Active", "Disabled"]},
        "#/properties/note": {"type": "string"},
    }

    def entry(**overrides: Any) -> dict[str, Any]:
        shaped = {
            "kind": "Command",
            "eventSubject": None,
            "versionMajor": 1,
            "shape": base_shape,
        }
        shaped.update(overrides)
        return shaped

    baseline = {"contracts": {"Foo": entry()}}

    # 1. Contract 从注册表移除
    breaking, _ = module.compare({}, baseline)
    assert any("Contract 从注册表移除" in item for item in breaking), breaking

    # 2. 类型变更 / enum 成员删除 / optional -> required
    breaking, _ = module.compare(
        {
            "Foo": entry(
                shape={
                    "#/properties/email": {"type": "integer"},
                    "#/properties/status": {"enum": ["Active"]},
                    "#/properties/note": {"type": "string", "required": True},
                }
            )
        },
        baseline,
    )
    joined = "\n".join(breaking)
    assert "type 由 string 变为 integer" in joined, joined
    assert "enum 成员被删除" in joined, joined
    assert "optional -> required" in joined, joined

    # 3. kind / eventSubject / version major 变更
    for overrides, needle in (
        ({"kind": "Query"}, "kind 由 Command 变为 Query"),
        ({"eventSubject": "event.x.y.v1"}, "eventSubject"),
        ({"versionMajor": 0}, "version major 降低"),
    ):
        reference = (
            {"contracts": {"Foo": entry(eventSubject="event.a.b.v1")}}
            if "eventSubject" in overrides
            else baseline
        )
        breaking, _ = module.compare({"Foo": entry(**overrides)}, reference)
        assert any(needle in item for item in breaking), f"{overrides}: {breaking}"

    # 4. 新增可选字段是 Non-breaking
    breaking, non_breaking = module.compare(
        {"Foo": entry(shape={**base_shape, "#/properties/added": {"type": "string"}})},
        baseline,
    )
    assert breaking == [], breaking
    assert any("新增字段节点" in item for item in non_breaking), non_breaking


def test_update_baseline_is_the_only_way_to_rebuild() -> None:
    """重建基线必须是显式动作，且内容可复现。"""
    module = _load_module()
    with tempfile.TemporaryDirectory() as tmp:
        target = Path(tmp) / "baseline.json"
        expected = module.build_baseline()
        target.write_text(json.dumps(expected, indent="\t"), encoding="utf-8")
        committed = json.loads(BASELINE.read_text(encoding="utf-8"))
        assert committed == expected, "基线可由 build_baseline() 复现"


def test_contract_ci_ledger_matches_section_55() -> None:
    ledger = yaml.safe_load(CI_LEDGER.read_text(encoding="utf-8"))
    obligations = ledger["obligations"]
    assert set(obligations) == set(DOC_28_SECTION_55), (
        f"义务账本与 doc 28 §55 不一致："
        f"缺失 {sorted(set(DOC_28_SECTION_55) - set(obligations))}，"
        f"多余 {sorted(set(obligations) - set(DOC_28_SECTION_55))}"
    )


def test_enforced_obligations_point_at_real_evidence() -> None:
    obligations = yaml.safe_load(CI_LEDGER.read_text(encoding="utf-8"))["obligations"]
    for name, entry in obligations.items():
        if entry["status"] != "enforced":
            continue
        evidence = REPO_ROOT / entry["evidence"]
        assert evidence.exists(), f"{name}: evidence 不存在 {entry['evidence']}"


def test_not_applicable_obligations_are_temporary_and_bounded() -> None:
    obligations = yaml.safe_load(CI_LEDGER.read_text(encoding="utf-8"))["obligations"]
    deferred = {name: e for name, e in obligations.items() if e["status"] != "enforced"}
    assert set(deferred) == {"consumer-contract-tests"}, (
        f"只允许 Consumer Contract Test 暂缓，实际: {sorted(deferred)}"
    )
    entry = deferred["consumer-contract-tests"]
    assert entry["status"] == "not-applicable"
    assert entry.get("reason"), "not-applicable 必须给出 reason"
    assert "mandatoryWhen" in entry, "not-applicable 必须给出转为 enforced 的触发条件"
