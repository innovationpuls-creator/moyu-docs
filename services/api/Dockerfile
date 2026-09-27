# Build the API and its pinned workspace dependencies from the repository lock.
FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim AS builder
WORKDIR /app
COPY . .
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-editable --package api-service

FROM python:3.12-slim AS runtime
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
