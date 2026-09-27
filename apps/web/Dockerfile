FROM node:24-bookworm-slim AS builder
WORKDIR /app
RUN corepack enable
COPY . .
RUN pnpm install --frozen-lockfile --filter @dom/web... \
    && pnpm --filter @dom/web build

FROM nginxinc/nginx-unprivileged:1.29-alpine AS runtime
COPY apps/web/nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=builder /app/apps/web/dist /usr/share/nginx/html
EXPOSE 8080
HEALTHCHECK --interval=15s --timeout=3s --start-period=5s --retries=5 \
    CMD wget -q -O /dev/null http://127.0.0.1:8080/healthz || exit 1
