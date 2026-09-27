FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim AS builder
WORKDIR /app
COPY . .
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-editable --package maintenance-worker

FROM python:3.12-slim AS runtime
ENV PATH="/app/.venv/bin:${PATH}" \
    PYTHONPATH=/app \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1
WORKDIR /app
RUN groupadd --system --gid 10001 dom \
    && useradd --system --uid 10001 --gid dom --home-dir /app --no-create-home dom
COPY --from=builder --chown=dom:dom /app/.venv /app/.venv
COPY --from=builder --chown=dom:dom /app/workers/maintenance /app/workers/maintenance
USER dom
CMD ["python", "-m", "workers.maintenance.main", "--daemon", "--interval", "5"]
