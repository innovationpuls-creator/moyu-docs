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

# 综合质量门禁：lint、typecheck、test 加契约兼容性与漂移校验
check: lint typecheck test contract-compat contract-drift

# 静态类型检查 (mypy)
typecheck:
    uv run mypy

# 运行单元测试 (pytest)
test:
    uv run pytest

# 运行 Phase 2 的真实 PostgreSQL 迁移与集成测试
# 可通过 DATABASE_URL 覆盖本地测试数据库连接。
test-db:
    uv run pytest tests/migration tests/integration

# 生成机器契约（registry 驱动，Python + TypeScript）
contract: generate-contracts

# 生成机器契约（由 scripts/generate_contracts.py 提供）
generate-contracts:
    uv run python scripts/generate_contracts.py

# 检测契约漂移（生成结果是否与 Contract Registry 一致，只读）
contract-drift:
    uv run python scripts/generate_contracts.py --check

# 检测 Breaking Contract Change（对照 contracts/registry-baseline.json）
contract-compat:
    uv run python scripts/check_contract_compat.py

# 重建契约基线（必须表现为一次可见的提交差异）
contract-baseline:
    uv run python scripts/check_contract_compat.py --update-baseline

# 校验冻结的仓库布局（docs/architecture/27 §3、§72）
layout-check:
    uv run python scripts/check_repository_layout.py
