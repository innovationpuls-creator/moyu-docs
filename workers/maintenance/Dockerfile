# Maintenance worker image (arch 15 §3): uv-managed Python runtime.
FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim AS builder
WORKDIR /app
COPY pyproject.toml uv.lock* ./
COPY workers/maintenance/pyproject.toml workers/maintenance/
COPY packages/py/core/pyproject.toml packages/py/core/
COPY packages/py/infrastructure/pyproject.toml packages/py/infrastructure/
COPY packages/py/task-runtime/pyproject.toml packages/py/task-runtime/ 2>/dev/null || true
RUN uv sync --frozen --no-dev --no-install-project 2>/dev/null || true

FROM python:3.12-slim
WORKDIR /app
ENV PYTHONPATH=/app/workers/maintenance:/app/packages/py/core/src:/app/packages/py/infrastructure/src:/app/packages/py/task-runtime/src
COPY workers/maintenance/workers workers/maintenance/workers 2>/dev/null || true
COPY workers/maintenance/main.py workers/maintenance/main.py 2>/dev/null || true
COPY packages/py/core/src packages/py/core/src 2>/dev/null || true
COPY packages/py/infrastructure/src packages/py/infrastructure/src 2>/dev/null || true
COPY packages/py/task-runtime/src packages/py/task-runtime/src 2>/dev/null || true
