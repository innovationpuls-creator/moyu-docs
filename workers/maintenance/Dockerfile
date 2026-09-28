# syntax=docker/dockerfile:1
# DOM maintenance worker 镜像（doc 26 §55：OCI Image / 多阶段 / 非 root）。
# 与 API 同构：uv 构建期 + python slim 运行期；不携带 contracts/migrations。
ARG UV_IMAGE=ghcr.io/astral-sh/uv:python3.12-bookworm-slim

FROM ${UV_IMAGE} AS build
WORKDIR /app
ARG PYPI_INDEX_URL=https://pypi.org/simple
ENV UV_DEFAULT_INDEX=${PYPI_INDEX_URL} \
    UV_LINK_MODE=copy
COPY . .
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-editable --package maintenance-worker

FROM python:3.12-slim AS runtime
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONPATH=/app \
    PATH="/app/.venv/bin:${PATH}"
WORKDIR /app
RUN groupadd --system --gid 10001 dom \
    && useradd --system --uid 10001 --gid dom --home-dir /app --no-create-home dom
COPY --link --from=build --chown=10001:10001 /app/.venv /app/.venv
COPY --link --from=build --chown=10001:10001 /app/workers /app/workers
USER dom
LABEL org.opencontainers.image.title="dom-maintenance-worker" \
      org.opencontainers.image.description="墨屿后台维护 Worker（checkpoint/purge/restore/import-export/webhook）"
CMD ["python", "-m", "workers.maintenance.main", "--daemon", "--production", "--interval", "5"]