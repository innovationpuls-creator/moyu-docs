# syntax=docker/dockerfile:1
# DOM API 服务镜像（doc 26 §55：OCI Image / 多阶段 / 非 root）。
# 构建期使用 uv 官方镜像（默认 ghcr.io，可用 UV_IMAGE 覆盖为镜像加速源），
# 运行期只携带 .venv + contracts + migrations，不含构建工具。
ARG UV_IMAGE=ghcr.io/astral-sh/uv:python3.12-bookworm-slim

FROM ${UV_IMAGE} AS build
WORKDIR /app
# 包索引可覆盖（国内部署可传阿里云 PyPI 镜像；非敏感值，落层可接受）。
ARG PYPI_INDEX_URL=https://pypi.org/simple
ENV UV_DEFAULT_INDEX=${PYPI_INDEX_URL} \
    UV_LINK_MODE=copy
COPY . .
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-editable --package api-service

FROM python:3.12-slim AS runtime
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PATH="/app/.venv/bin:${PATH}" \
    CONTRACTS_DIR=/app/contracts
WORKDIR /app
RUN groupadd --system --gid 10001 dom \
    && useradd --system --uid 10001 --gid dom --home-dir /app --no-create-home dom
COPY --link --from=build --chown=10001:10001 /app/.venv /app/.venv
COPY --link --from=build --chown=10001:10001 /app/contracts /app/contracts
COPY --link --from=build --chown=10001:10001 /app/migrations /app/migrations
USER dom
EXPOSE 8000
LABEL org.opencontainers.image.title="dom-api" \
      org.opencontainers.image.description="墨屿 HTTP API 服务"
HEALTHCHECK --interval=15s --timeout=3s --start-period=20s --retries=5 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/healthz', timeout=2)" || exit 1
CMD ["uvicorn", "api.main:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers"]