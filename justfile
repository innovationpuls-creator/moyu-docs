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
