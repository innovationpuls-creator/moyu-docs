#!/usr/bin/env python3
"""Generate the Python projection of /contracts (doc 27 §17/§25/§53, doc 28 §46/§61.11).

Deterministic, hermetic generator + drift checker for ``app_contracts.models``.
Driven by ``contracts/openapi/client-api.yaml`` with ``--openapi-scopes paths``.

This script is the single source of truth for the generated artifact
``packages/py/contracts/src/app_contracts/models.py``. Never hand-edit the output;
rerun this script instead. Importable (``compare_generated`` / ``run_codegen`` /
``format_file``) so ``tests/contract/test_contract_drift.py`` can exercise it
without a subprocess and prove the drift gate is real, not a habit.
"""

from __future__ import annotations

import difflib
import subprocess
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
OPENAPI = REPO_ROOT / "contracts" / "openapi" / "client-api.yaml"
OUTPUT = (
    REPO_ROOT / "packages" / "py" / "contracts" / "src" / "app_contracts" / "models.py"
)
RUFF_CONFIG = REPO_ROOT / "pyproject.toml"


def run_codegen(output: Path) -> None:
    """Invoke datamodel-codegen as a module; never depend on a PATH binary."""
    output.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        sys.executable,
        "-m",
        "datamodel_code_generator",
        "--input",
        str(OPENAPI),
        "--input-file-type",
        "openapi",
        "--openapi-scopes",
        "paths",
        "--output",
        str(output),
        "--output-model-type",
        "pydantic_v2.BaseModel",
        "--use-standard-collections",
        "--use-title-as-name",
        "--collapse-root-models",
        "--disable-timestamp",
    ]
    res = subprocess.run(cmd, capture_output=True, text=True)
    if res.returncode != 0:
        raise RuntimeError(f"codegen failed:\n{res.stderr}")


def format_file(path: Path) -> None:
    """Deterministically ruff --fix then ruff format with the repo config."""
    config = str(RUFF_CONFIG)
    # E501 is ignored for generated files: datamodel-codegen emits the long
    # `details` description from contracts/errors/error-envelope.schema.json as a
    # single string literal that the formatter cannot wrap (doc 28 §31). The
    # committed artifact's E501 is covered by [tool.ruff.lint.per-file-ignores]
    # in the root pyproject; this flag mirrors it for the temp file outside the
    # repo path so the check step stays deterministic.
    steps = (
        ["check", "--fix", "--config", config, "--ignore", "E501"],
        ["format", "--config", config],
    )
    for step in steps:
        res = subprocess.run(
            [sys.executable, "-m", "ruff", *step, str(path)],
            capture_output=True,
            text=True,
        )
        if res.returncode != 0:
            raise RuntimeError(f"ruff {' '.join(step)} failed:\n{res.stderr}")


def compare_generated(committed: Path, generated: Path) -> list[str]:
    """Return [] when identical, else a concrete drift summary (no mutation)."""
    a = committed.read_text(encoding="utf-8").splitlines()
    b = generated.read_text(encoding="utf-8").splitlines()
    if a == b:
        return []
    diff = list(difflib.unified_diff(a, b, lineterm=""))
    added = sum(1 for ln in diff if ln.startswith("+") and not ln.startswith("+++"))
    removed = sum(1 for ln in diff if ln.startswith("-") and not ln.startswith("---"))
    return [f"drift: +{added} / -{removed} lines", *diff[:40]]


def main(argv: list[str]) -> int:
    if "--check" in argv:
        if (
            subprocess.run(
                ["git", "check-ignore", "-q", str(OUTPUT)], cwd=REPO_ROOT
            ).returncode
            == 0
        ):
            print("DRIFT FAIL：生成产物被 git 忽略，无法做漂移保护")
            return 1
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td) / "models.py"
            run_codegen(tmp)
            format_file(tmp)
            text = tmp.read_text(encoding="utf-8")
            if not text.strip() or "class " not in text:
                print("DRIFT FAIL：生成内容为空或不含 class 定义")
                return 1
            drift = compare_generated(OUTPUT, tmp)
            if drift:
                print("DRIFT FAIL：检测到生成漂移")
                print("\n".join(drift))
                return 1
        print("PASS：生成产物与提交物一致，无漂移")
        return 0

    run_codegen(OUTPUT)
    format_file(OUTPUT)
    print(f"PASS：已生成 {OUTPUT.relative_to(REPO_ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
