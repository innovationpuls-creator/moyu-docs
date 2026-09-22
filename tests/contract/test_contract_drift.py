"""契约代码生成门禁（docs/architecture/28 §2.1 / §42-§48 / §55-§56）。

覆盖：
1. ``--check`` 通过：生成物与 Contract Registry 一致。
2. 确定性：两次独立生成的产物逐字节一致。
3. ``--check`` 只读：不修改工作区。
4. 注册即生成：五种 kind 都有 Python 与 TypeScript 投影，包含不承载 HTTP Route 的
   Event 与未路由的 Query。
5. no-body Contract 不生成占位请求模型。
6. 生成物带生成器头，且没有同名 schema 派生出的数字后缀类名。
7. 反向守卫：比对函数必须真的能报出漂移。
"""

from __future__ import annotations

import importlib
import importlib.util
import pkgutil
import re
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
GENERATOR = REPO_ROOT / "scripts" / "generate_contracts.py"
PY_PACKAGE = REPO_ROOT / "packages" / "py" / "contracts" / "src" / "app_contracts"
TS_PACKAGE = REPO_ROOT / "packages" / "ts" / "contracts" / "src"

# docs/product/features/account-auth-session.md §3.1
EXPECTED_ACCOUNT_STATES = {
    "PendingVerification",
    "Active",
    "Disabled",
    "DeletionPending",
    "Deleted",
}
# docs/architecture/00-ARCHITECTURE-CONSTITUTION.md §3.19
EXPECTED_ERROR_CATEGORIES = {
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
# registry requestBody: none —— 生成物中只应有 Response 类型
NO_BODY_LOGICAL_NAMES = (
    "Logout",
    "RequestAccountDeletion",
    "CancelAccountDeletion",
    "GetCurrentAccount",
    "GetCurrentSession",
    "GetAccountStatus",
)


def _load_generator() -> Any:
    assert GENERATOR.is_file(), f"缺少生成器脚本: {GENERATOR}"
    spec = importlib.util.spec_from_file_location("gen_contracts", GENERATOR)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load generator module from {GENERATOR}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _run_generator(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(GENERATOR), *args],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )


def _tree_digest(root: Path) -> dict[str, bytes]:
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def _contract_modules() -> list[Any]:
    """导入生成包中的全部契约模块。"""
    package = importlib.import_module("app_contracts")
    modules = [package]
    for info in pkgutil.walk_packages(package.__path__, prefix="app_contracts."):
        modules.append(importlib.import_module(info.name))
    return modules


def _find_symbol(name: str) -> Any:
    for module in _contract_modules():
        found = getattr(module, name, None)
        if found is not None:
            return found
    raise AssertionError(f"{name} 未出现在任何生成的契约模块中")


def test_drift_check_passes_against_registry() -> None:
    result = _run_generator("--check")
    assert result.returncode == 0, (
        f"契约漂移检查失败 (exit {result.returncode})\n"
        f"--- stdout ---\n{result.stdout}\n--- stderr ---\n{result.stderr}"
    )


def test_generation_is_deterministic() -> None:
    generator = _load_generator()
    with tempfile.TemporaryDirectory() as first:
        with tempfile.TemporaryDirectory() as second:
            generator.generate_all(Path(first))
            generator.generate_all(Path(second))
            for language in ("python", "typescript"):
                a = _tree_digest(Path(first) / language)
                b = _tree_digest(Path(second) / language)
                assert a == b, (
                    f"{language} 两次生成结果不一致：生成器不是确定性的"
                    f"（差异文件：{sorted(set(a) ^ set(b))[:5]}）"
                )


def test_check_mode_does_not_mutate_the_worktree() -> None:
    before = _tree_digest(PY_PACKAGE)
    ts_before = _tree_digest(TS_PACKAGE)
    result = _run_generator("--check")
    assert result.returncode == 0, result.stdout + result.stderr
    assert _tree_digest(PY_PACKAGE) == before, "--check 修改了 Python 生成物"
    assert _tree_digest(TS_PACKAGE) == ts_before, "--check 修改了 TypeScript 生成物"


def test_generated_python_contracts_cover_every_kind() -> None:
    """注册即生成：Command / Query / Event / Error / Identity 五类都要有投影。"""
    # Command
    assert _find_symbol("RegisterWithEmail") is not None
    # Query（GetAccountStatus 无 HTTP Route 依赖，仍必须有投影）
    assert _find_symbol("GetAccountStatusResponse") is not None
    # Event（不承载 HTTP Route）
    assert _find_symbol("SessionReplaced") is not None
    assert _find_symbol("SessionReplacedPayload") is not None
    # Error
    assert _find_symbol("ErrorEnvelope") is not None
    # Identity
    assert _find_symbol("NodeRef") is not None


def test_generated_enums_match_canonical_contracts() -> None:
    account_status = _find_symbol("AccountStatusValue")
    assert {member.value for member in account_status} == EXPECTED_ACCOUNT_STATES
    categories = _find_symbol("AuthErrorCategory")
    assert {member.value for member in categories} == EXPECTED_ERROR_CATEGORIES


def test_generated_typescript_contracts_cover_every_kind() -> None:
    expectations = {
        "queries/auth/get-account-status.d.ts": ["GetAccountStatusResponse"],
        "events/auth/session-replaced.d.ts": [
            "SessionReplaced",
            "SessionReplacedPayload",
            "SessionReplacementReason",
        ],
        "errors/error-envelope.d.ts": ["ErrorEnvelope"],
        "ids/ids.d.ts": ["NodeRef"],
        "commands/auth/register-with-email.d.ts": ["RegisterWithEmail"],
        "commands/auth/register-with-email-response.d.ts": [
            "RegisterWithEmailResponse"
        ],
        "commands/auth/login-with-password-response.d.ts": [
            "LoginWithPasswordResponse"
        ],
    }
    for relative, names in expectations.items():
        path = TS_PACKAGE / relative
        assert path.is_file(), f"缺少 TypeScript 投影: {relative}"
        text = path.read_text(encoding="utf-8")
        for name in names:
            assert re.search(
                rf"^export (interface|type) {name}\b", text, re.MULTILINE
            ), f"{relative} 缺少导出 {name}"


def test_no_body_contracts_have_no_request_model() -> None:
    """no-body Contract 不得生成占位请求模型（doc 28 §8）。"""
    python_names = {
        name
        for module in _contract_modules()
        for name in dir(module)
        if name[:1].isupper()
    }
    for logical in NO_BODY_LOGICAL_NAMES:
        assert logical not in python_names, (
            f"{logical}: no-body Contract 不应生成请求模型 {logical}"
        )
        assert f"{logical}Response" in python_names, (
            f"{logical}: 缺少响应模型 {logical}Response"
        )
        ts_file = next(
            TS_PACKAGE.rglob(
                f"{'-'.join(re.findall(r'[A-Z][a-z]*', logical)).lower()}.d.ts"
            ),
            None,
        )
        assert ts_file is not None, f"{logical}: 缺少 TypeScript 投影"
        text = ts_file.read_text(encoding="utf-8")
        assert (
            re.search(rf"^export (interface|type) {logical}\b", text, re.MULTILINE)
            is None
        ), f"{logical}: no-body Contract 的 TS 投影不应声明请求类型"


def test_generated_artifacts_are_marked_and_collision_free() -> None:
    for path in sorted(PY_PACKAGE.rglob("*.py")):
        text = path.read_text(encoding="utf-8")
        assert text.startswith("# generated by datamodel-codegen"), (
            f"{path.name} 缺少生成器头，疑似手工编辑（doc 28 §61.11）"
        )
        collisions = [
            name
            for name in re.findall(
                r"^class ([A-Za-z_][A-Za-z0-9_]*)", text, re.MULTILINE
            )
            if name[-1].isdigit()
        ]
        assert not collisions, f"{path.name}: 类名冲突 {collisions}"


def test_drift_comparator_ignores_python_runtime_artifacts() -> None:
    """运行时 Python 缓存不是生成契约，不能触发漂移。"""
    generator = _load_generator()
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        committed = root / "committed"
        generated = root / "generated"
        committed.mkdir()
        (committed / "a.py").write_bytes(b"class A:\n    pass\n")
        generated.mkdir()
        (generated / "a.py").write_bytes(b"class A:\n    pass\n")
        cache = generated / "__pycache__"
        cache.mkdir()
        (cache / "a.cpython-312.pyc").write_bytes(b"runtime cache")

        assert generator.compare_generated(committed, generated) == []


def test_drift_comparator_reports_real_drift() -> None:
    """反向守卫：比对函数必须真的能报出漂移，不能永远返回空。"""
    generator = _load_generator()
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        committed = root / "committed"
        changed = root / "changed"
        extra = root / "extra"
        empty = root / "empty"
        for target, files in (
            (committed, {"a.py": b"class A:\n    pass\n"}),
            (changed, {"a.py": b"class A:\n    changed\n"}),
            (extra, {"a.py": b"class A:\n    pass\n", "b.py": b"class B:\n    pass\n"}),
            (empty, {}),
        ):
            target.mkdir(parents=True)
            for name, content in files.items():
                (target / name).write_bytes(content)

        assert generator.compare_generated(committed, committed) == []
        missing = generator.compare_generated(extra, committed)
        assert any("缺少" in problem for problem in missing), missing
        surplus = generator.compare_generated(committed, extra)
        assert any("多余" in problem for problem in surplus), surplus
        differing = generator.compare_generated(committed, changed)
        assert any("内容不一致" in problem for problem in differing), differing
        blank = generator.compare_generated(committed, empty)
        assert any("为空" in problem for problem in blank), blank
