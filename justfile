# Root Task Runner for DOM Monorepo (justfile)
# See docs/architecture/26-Technology-Stack-Decision.md §53

# 默认列出所有可用任务
default:
    @just --list

# 全局代码检查 (Python + Frontend JS/TS/JSON)
lint: lint-py lint-js

# 全局代码自动修复与净化 (Python + Frontend JS/TS/JSON)
format: format-py format-js

# Python 代码检查 (Ruff)
lint-py:
    uv run ruff check .

# Python 代码自动修复与格式化 (Ruff: 清除未使用的 import/变量并排版)
format-py:
    uv run ruff check --fix .
    uv run ruff format .

# 前端与配置文件检查 (Biome)
lint-js:
    pnpm exec biome check .

# 前端与配置文件自动修复与格式化 (Biome: 清除废弃引用并排版)
format-js:
    pnpm exec biome check --write .

# 综合质量门禁：依次执行 lint、typecheck、test
check: lint typecheck test

# 静态类型检查 (mypy)
typecheck:
    uv run mypy

# 运行单元测试 (pytest)
test:
    uv run pytest

# 生成机器契约（由 Task 3 提供脚本）
contract: generate-contracts

# 生成机器契约（由 Task 3 提供脚本）
generate-contracts:
    uv run python scripts/generate_contracts.py

# 检测契约漂移（生成结果是否与源码一致）
contract-drift:
    uv run python scripts/generate_contracts.py --check

# 校验冻结的仓库布局（docs/architecture/27 §3、§72）
layout-check:
    uv run python scripts/check_repository_layout.py
