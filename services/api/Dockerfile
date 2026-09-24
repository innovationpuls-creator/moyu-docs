# API service image (arch 15 §3): uv-managed Python 3.12 runtime.
FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim AS builder
WORKDIR /app
COPY pyproject.toml uv.lock* ./
COPY services/api/pyproject.toml services/api/
COPY packages/py/core/pyproject.toml packages/py/core/
COPY packages/py/infrastructure/pyproject.toml packages/py/infrastructure/
COPY packages/py/contracts/pyproject.toml packages/py/contracts/
RUN uv sync --frozen --no-dev --no-install-project

FROM python:3.12-slim
WORKDIR /app
ENV PYTHONPATH=/app/services/api/src:/app/packages/py/core/src:/app/packages/py/infrastructure/src
COPY --from=builder /app/.venv .venv
COPY services/api/src services/api/src
COPY packages/py/core/src packages/py/core/src
COPY packages/py/infrastructure/src packages/py/infrastructure/src
COPY packages/py/contracts/src packages/py/contracts/src
EXPOSE 8000
CMD [".venv/bin/uvicorn", "api.main:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000"]
