#!/usr/bin/env python3
"""契约代码生成器 + 漂移检查（docs/architecture/28 §2.1 / §42-§48 / §55-§56）。

输入 Source 是 `contracts/registry.yaml`：遍历其中注册的每一条 Contract，按其
`schemaPath` 读取 Canonical JSON Schema。注册即生成，因此 `Command` / `Query` /
`Event` / `Error` / `Identity` 五种 kind 都有语言投影 —— 包括不承载 HTTP Route 的
Event。`contracts/openapi/client-api.yaml` 只用于生成 HTTP Client 面类型，不作为
“是否生成某条契约”的判据。

```text
registry.yaml
  → staging（规范化：扩展名归一、$ref 后缀归一、去掉绝对 $id）
      → Python: datamodel-codegen            → packages/py/contracts/src/app_contracts
      → TypeScript: json-schema-to-typescript → packages/ts/contracts/src
  → OpenAPI → openapi-typescript → packages/ts/contracts/src/client-api.d.ts
```

规范化说明：canonical schema 各自声明绝对 `$id`（例如
`https://contracts.dom.internal/...`）。第三方引用解析器会把该 `$id` 当作 base URI，
进而按 URL 取文件，离线环境下必然失败。staging 因此去掉 `$id` 并把 `$ref` 里的
`.schema.json` 归一为 `.json`；canonical 文件本身保持原样。

确定性：`--disable-timestamp` + 固定 staging 目录名（生成物头部会写入输入目录名）
+ 生成后统一 ruff 格式化。`--check` 生成到临时目录逐字节比对，绝不修改工作区。
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
REGISTRY = REPO_ROOT / "contracts" / "registry.yaml"
CONTRACTS_DIR = REPO_ROOT / "contracts"
OPENAPI = CONTRACTS_DIR / "openapi" / "client-api.yaml"
RUFF_CONFIG = REPO_ROOT / "pyproject.toml"
BIOME_CONFIG = REPO_ROOT / "biome.json"

PY_PACKAGE = REPO_ROOT / "packages" / "py" / "contracts" / "src" / "app_contracts"
TS_PACKAGE = REPO_ROOT / "packages" / "ts" / "contracts" / "src"
# 非生成物：清理与漂移比对时豁免（doc 27 §18 只约束生成物本身）
PY_KEEP = {"py.typed"}
# 固定 staging 目录名：datamodel-codegen 会把输入目录名写进每个生成文件头部
STAGING_DIR_NAME = "contracts"

PY_CODEGEN_ARGS = [
    "--input-file-type",
    "jsonschema",
    "--output-model-type",
    "pydantic_v2.BaseModel",
    "--use-standard-collections",
    "--use-title-as-name",
    "--collapse-root-models",
    "--disable-timestamp",
]

# E501 显式忽略：临时输出目录不在仓库内，per-file-ignores 无法命中，
# 只有两个模式用同一套参数才能保证生成结果逐字节一致。
RUFF_STEPS = (
    ["check", "--fix", "--config", str(RUFF_CONFIG), "--ignore", "E501"],
    ["format", "--config", str(RUFF_CONFIG)],
)


def _run(cmd: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, cwd=REPO_ROOT, capture_output=True, text=True)


def registered_contracts() -> list[dict]:
    """按 registry.yaml 的注册顺序返回 Contract 列表（生成顺序即注册顺序）。"""
    data = yaml.safe_load(REGISTRY.read_text(encoding="utf-8"))
    contracts = data.get("contracts")
    if not isinstance(contracts, list) or not contracts:
        raise RuntimeError(f"{REGISTRY} 中没有注册任何 Contract")
    return contracts


def _normalise(node: object) -> object:
    """去掉绝对 $id；把 $ref 中的 .schema.json 后缀归一为 .json。"""
    if isinstance(node, dict):
        normalised: dict[str, object] = {}
        for key, value in node.items():
            if key == "$id":
                continue
            if key == "$ref" and isinstance(value, str):
                normalised[key] = value.replace(".schema.json", ".json")
            else:
                normalised[key] = _normalise(value)
        return normalised
    if isinstance(node, list):
        return [_normalise(item) for item in node]
    return node


def _staged_rel(schema_path: str) -> Path:
    """canonical schemaPath -> staging 内相对路径（扩展名归一为 .json）。"""
    relative = Path(schema_path).relative_to("contracts")
    return relative.with_name(relative.name.replace(".schema.json", ".json"))


def stage_schemas(dest: Path) -> list[Path]:
    """把注册的 Canonical Schema 规范化复制到 dest，返回落盘路径列表。"""
    staged: list[Path] = []
    for entry in registered_contracts():
        source = REPO_ROOT / entry["schemaPath"]
        if not source.is_file():
            raise FileNotFoundError(
                f"{entry['logicalName']}: 缺少 Canonical Schema {source}"
            )
        target = dest / _staged_rel(entry["schemaPath"])
        target.parent.mkdir(parents=True, exist_ok=True)
        document = _normalise(json.loads(source.read_text(encoding="utf-8")))
        target.write_text(
            json.dumps(document, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )
        staged.append(target)
    return staged


def build_staging(root: Path) -> Path:
    staging = root / STAGING_DIR_NAME
    staging.mkdir(parents=True, exist_ok=True)
    stage_schemas(staging)
    return staging


def build_ts_staging(root: Path) -> Path:
    """TypeScript 专用 staging：把 response 提升为独立 root 文件。

    datamodel-codegen 会输出每个输入文件的全部 ``$defs``，但
    json-schema-to-typescript 只输出可达类型 —— 响应放在 ``$defs.<Name>Response``
    时不会被投影。因此对 requestBody: required 的契约额外落一份以响应为 root 的
    文件；no-body 契约的 root 本来就是响应，无需提升。
    """
    staging = build_staging(root)
    for entry in registered_contracts():
        if entry["kind"] not in ("Command", "Query"):
            continue
        target = staging / _staged_rel(entry["schemaPath"])
        document = json.loads(target.read_text(encoding="utf-8"))
        defs = document.get("$defs") or {}
        response_key = f"{entry['logicalName']}Response"
        response = defs.get(response_key)
        if not isinstance(response, dict):
            continue
        promoted = dict(response)
        promoted["$schema"] = document["$schema"]
        remaining = {key: value for key, value in defs.items() if key != response_key}
        if remaining:
            promoted["$defs"] = remaining
        promoted_path = target.with_name(f"{target.stem}-response.json")
        promoted_path.write_text(
            json.dumps(promoted, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )
    return staging


def generate_python(staging: Path, output: Path) -> None:
    """datamodel-codegen：一个 Canonical Schema 一个模块，目录结构镜像 /contracts。"""
    output.mkdir(parents=True, exist_ok=True)
    result = _run(
        [
            sys.executable,
            "-m",
            "datamodel_code_generator",
            "--input",
            str(staging),
            "--output",
            str(output),
            *PY_CODEGEN_ARGS,
        ]
    )
    if result.returncode != 0:
        raise RuntimeError(f"datamodel-codegen 失败:\n{result.stdout}\n{result.stderr}")
    for step in RUFF_STEPS:
        lint = _run([sys.executable, "-m", "ruff", *step, str(output)])
        if lint.returncode != 0:
            raise RuntimeError(f"ruff {step[0]} 失败:\n{lint.stdout}\n{lint.stderr}")


def generate_typescript(staging: Path, output: Path) -> None:
    """json-schema-to-typescript：同样按注册集生成，覆盖全部 kind。"""
    output.mkdir(parents=True, exist_ok=True)
    result = _run(
        [
            "node",
            str(REPO_ROOT / "scripts" / "generate_ts_contracts.mjs"),
            str(staging),
            str(output),
        ]
    )
    if result.returncode != 0:
        raise RuntimeError(f"TS 契约生成失败:\n{result.stdout}\n{result.stderr}")


def format_typescript(output: Path) -> None:
    """biome 统一格式化 TypeScript 生成物。

    biome 拥有仓库的风格定义；由生成器而不是人工保证排版一致，两个模式（就地生成 /
    ``--check``）才会产出逐字节相同的文件。必须在所有 TS 产物写完之后调用。
    """
    formatted = _run(
        [
            "pnpm",
            "exec",
            "biome",
            "check",
            "--write",
            f"--config-path={BIOME_CONFIG}",
            str(output),
        ]
    )
    if formatted.returncode != 0:
        raise RuntimeError(
            f"biome 格式化 TS 生成物失败:\n{formatted.stdout}\n{formatted.stderr}"
        )


def generate_openapi_types(output: Path) -> None:
    """openapi-typescript：只描述 HTTP Client 面（doc 28 §43）。

    输入输出都用绝对路径：``--check`` 会在临时目录里生成，不能让路径假定自己在仓库内。
    """
    output.parent.mkdir(parents=True, exist_ok=True)
    result = _run(
        [
            "pnpm",
            "exec",
            "openapi-typescript",
            str(OPENAPI),
            "-o",
            str(output),
        ]
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"openapi-typescript 失败:\n{result.stdout}\n{result.stderr}"
        )


def generate_all(root: Path) -> dict[str, Path]:
    """在 root 下生成全部产物，返回 {目标语言: 输出目录}。"""
    python_out = root / "py"
    ts_out = root / "ts"
    generate_python(build_staging(root / "py-staging"), python_out)
    generate_typescript(build_ts_staging(root / "ts-staging"), ts_out)
    generate_openapi_types(ts_out / "client-api.d.ts")
    format_typescript(ts_out)
    return {"python": python_out, "typescript": ts_out}


def generated_files(root: Path, keep: set[str]) -> dict[str, bytes]:
    """枚举生成物：相对路径 -> 内容。keep 中的文件名豁免。"""
    files: dict[str, bytes] = {}
    for path in sorted(root.rglob("*")):
        if (
            path.is_file()
            and path.name not in keep
            and "__pycache__" not in path.parts
            and path.suffix not in {".pyc", ".pyo"}
        ):
            files[path.relative_to(root).as_posix()] = path.read_bytes()
    return files


def compare_generated(
    committed: Path, generated: Path, keep: set[str] | None = None
) -> list[str]:
    """返回漂移问题列表；空列表表示无漂移。纯读取，不做任何写操作。"""
    keep = keep or set()
    if not generated.is_dir():
        return [f"没有生成任何产物: {generated}"]
    actual = generated_files(generated, keep)
    if not actual:
        return [f"生成结果为空: {generated}"]
    if not committed.is_dir():
        return [f"缺少已提交的生成物目录: {committed}"]
    expected = generated_files(committed, keep)
    if not expected:
        return [f"已提交的生成物目录为空: {committed}"]
    problems = [
        f"漂移: 生成物中缺少 {name}" for name in sorted(set(expected) - set(actual))
    ]
    problems += [
        f"漂移: 出现多余文件 {name}" for name in sorted(set(actual) - set(expected))
    ]
    problems += [
        f"漂移: {name} 内容不一致"
        for name in sorted(set(actual) & set(expected))
        if actual[name] != expected[name]
    ]
    return problems


def _clear_generated(root: Path, keep: set[str]) -> None:
    """清空生成物目录，保留 keep 中的非生成文件（仅默认生成模式调用）。"""
    if not root.is_dir():
        return
    for path in sorted(root.rglob("*"), reverse=True):
        if path.is_file():
            if path.name not in keep:
                path.unlink()
        elif path.is_dir() and not any(path.iterdir()):
            path.rmdir()


def _git_ignored(path: Path) -> bool:
    return _run(["git", "check-ignore", "-q", str(path)]).returncode == 0


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="契约代码生成与漂移检查")
    parser.add_argument("--check", action="store_true", help="仅校验漂移，不修改工作区")
    args = parser.parse_args(argv)

    if not args.check:
        _clear_generated(PY_PACKAGE, PY_KEEP)
        _clear_generated(TS_PACKAGE, set())
        with tempfile.TemporaryDirectory() as tmp:
            generate_python(build_staging(Path(tmp) / "py-staging"), PY_PACKAGE)
            generate_typescript(build_ts_staging(Path(tmp) / "ts-staging"), TS_PACKAGE)
            generate_openapi_types(TS_PACKAGE / "client-api.d.ts")
            format_typescript(TS_PACKAGE)
        print(
            f"PASS：已生成 {PY_PACKAGE.relative_to(REPO_ROOT)} 与 "
            f"{TS_PACKAGE.relative_to(REPO_ROOT)}"
        )
        return 0

    problems: list[str] = []
    for target in (PY_PACKAGE, TS_PACKAGE):
        if _git_ignored(target):
            problems.append(f"生成目录被 .gitignore 忽略，漂移检查失效: {target}")
    with tempfile.TemporaryDirectory() as tmp:
        generated = generate_all(Path(tmp))
        problems += [
            f"[python] {item}"
            for item in compare_generated(PY_PACKAGE, generated["python"], PY_KEEP)
        ]
        problems += [
            f"[typescript] {item}"
            for item in compare_generated(TS_PACKAGE, generated["typescript"])
        ]
    if problems:
        print("FAIL：契约生成物存在漂移（docs/architecture/28 §55-§56）")
        for problem in problems:
            print(f"  - {problem}")
        print("\n请执行 `just contract` 重新生成并提交生成物。")
        return 1
    print("PASS：契约生成物与 Contract Registry 一致，无漂移")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
