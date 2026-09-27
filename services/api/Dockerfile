# Build the API and its pinned workspace dependencies from the repository lock.
ARG UV_IMAGE=ghcr.io/astral-sh/uv:python3.12-bookworm-slim@sha256:e5b65587bce7de595f299855d7385fe7fca39b8a74baa261ba1b7147afa78e58
ARG PYTHON_IMAGE=python:3.12-slim@sha256:f77ac9e44ae96ef2c90b8053ea08c31f8be030f824196b0ae4db6d462c84e51f
FROM ${UV_IMAGE} AS builder
ARG UV_LOCK_MIRROR_BASE=
WORKDIR /app
COPY . .
RUN --mount=type=cache,target=/root/.cache/uv \
    if [ -n "$UV_LOCK_MIRROR_BASE" ]; then \
        sed -i \
            -e "s#https://pypi.org/simple#${UV_LOCK_MIRROR_BASE}/simple#g" \
            -e "s#https://files.pythonhosted.org#${UV_LOCK_MIRROR_BASE}#g" \
            uv.lock; \
    fi \
    && uv sync --frozen --no-dev --no-editable --package api-service

FROM ${PYTHON_IMAGE} AS runtime
ENV PATH="/app/.venv/bin:${PATH}" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1
WORKDIR /app
RUN groupadd --system --gid 10001 dom \
    && useradd --system --uid 10001 --gid dom --home-dir /app --no-create-home dom
COPY --from=builder --chown=dom:dom /app/.venv /app/.venv
COPY --from=builder --chown=dom:dom /app/contracts /app/contracts
COPY --from=builder --chown=dom:dom /app/migrations /app/migrations
ENV CONTRACTS_DIR=/app/contracts
USER dom
EXPOSE 8000
HEALTHCHECK --interval=15s --timeout=3s --start-period=20s --retries=5 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/healthz', timeout=2)" || exit 1
CMD ["uvicorn", "api.main:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers"]
