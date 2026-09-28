# Root Task Runner for 墨屿 Monorepo (justfile)
# See docs/architecture/26-Technology-Stack-Decision.md §53

# 默认列出所有可用任务
default:
    @just --list

# Start the local API with the ignored, persistent root .env configuration.
dev-api:
    test -f .env || (echo "Create the root .env before starting the API." >&2; exit 1)
    uv run --env-file .env --project services/api python -c 'import uvicorn; from api.main import create_app; uvicorn.run(create_app(debug=True), host="127.0.0.1", port=8000, log_level="info")'

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

# 运行真实 PostgreSQL 迁移与集成测试；只允许专用隔离测试库。
test-db:
    test -n "$DATABASE_URL" || (echo "DATABASE_URL must target dom_workspace_lifecycle_test" >&2; exit 1)
    uv run python -c 'from urllib.parse import urlparse; import os; url=os.environ["DATABASE_URL"].replace("postgresql+psycopg://", "postgresql://", 1); assert urlparse(url).path.lstrip("/") == "dom_workspace_lifecycle_test", "DATABASE_URL must target dom_workspace_lifecycle_test"'
    PYTHONPATH=.:packages/py/task-runtime/src:packages/py/core/src uv run pytest tests/migration tests/integration

# 运行 Realtime WebSocket 测试与类型检查 (@dom/realtime; vitest, 真实 Valkey db 15)
test-realtime:
    pnpm --filter @dom/realtime test
    pnpm --filter @dom/realtime typecheck

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

# 完整 Release Gate（arch 24）：lint + typecheck + 契约 + 受保护 DB 回归 +
# 安全/迁移闸 + 浏览器套件。DATABASE_URL 必须指向隔离测试库。
ts-packages:
    pnpm --filter @dom/yjs-runtime test
    pnpm --filter @dom/yjs-runtime typecheck
    pnpm --filter @dom/editor-core test
    pnpm --filter @dom/editor-core typecheck

dr-check:
    DATABASE_URL=postgresql+psycopg://torch@localhost:5432/dom_workspace_lifecycle_test uv run python scripts/dr_schema_check.py

dr-sizing:
    DATABASE_URL=postgresql+psycopg://torch@localhost:5432/dom_workspace_lifecycle_test uv run python scripts/dr_sizing.py

dr-load:
    DATABASE_URL=postgresql+psycopg://torch@localhost:5432/dom_workspace_lifecycle_test uv run python scripts/dr_load_probe.py

check-full: lint layout-check typecheck ts-packages dr-check contract-compat contract-drift
    test -n "$DATABASE_URL" || (echo "DATABASE_URL must target dom_workspace_lifecycle_test" >&2; exit 1)
    uv run python -c 'from urllib.parse import urlparse; import os; url=os.environ["DATABASE_URL"].replace("postgresql+psycopg://", "postgresql://", 1); assert urlparse(url).path.lstrip("/") == "dom_workspace_lifecycle_test", "DATABASE_URL must target dom_workspace_lifecycle_test"'
    PYTHONPATH=.:packages/py/task-runtime/src:packages/py/core/src uv run pytest --import-mode=importlib packages/py/core/tests packages/py/task-runtime/tests packages/py/infrastructure/tests/postgres packages/py/infrastructure/tests/nats tests/integration/task tests/security/task tests/bdd/async-task-execution tests/security/lifecycle-purge tests/bdd/lifecycle-purge tests/security/resource-content tests/bdd/resource-content tests/bdd/history tests/security/migrations workers/maintenance services/api/tests
    uv run pytest tests/contract --ignore=tests/contract/test_contract_ci.py
    uv run python scripts/generate_contracts.py --check
    git diff --check
