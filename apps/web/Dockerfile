# syntax=docker/dockerfile:1
# DOM web 前端镜像（doc 26 §55：OCI Image / 多阶段 / 非 root）。
# 构建期：Vite 产出纯静态 dist；运行期：非 root nginx 提供静态文件并反代
# /v1（API）与 WebSocket（realtime），浏览器同源访问（无 CORS）。
FROM node:24-bookworm-slim AS build
WORKDIR /app
ARG NPM_REGISTRY=https://registry.npmjs.org/
ENV npm_config_registry=${NPM_REGISTRY}
RUN corepack enable
# 先复制 lock 与全部 workspace 包 manifest，最大化依赖层缓存命中。
COPY package.json pnpm-workspace.yaml pnpm-lock.yaml ./
COPY apps/web/package.json apps/web/package.json
COPY packages/ts/client-sdk/package.json packages/ts/client-sdk/package.json
COPY packages/ts/contracts/package.json packages/ts/contracts/package.json
COPY packages/ts/editor-core/package.json packages/ts/editor-core/package.json
COPY packages/ts/realtime-client/package.json packages/ts/realtime-client/package.json
COPY packages/ts/realtime-protocol/package.json packages/ts/realtime-protocol/package.json
COPY packages/ts/resource-runtime/package.json packages/ts/resource-runtime/package.json
COPY packages/ts/yjs-runtime/package.json packages/ts/yjs-runtime/package.json
RUN --mount=type=cache,target=/root/.local/share/pnpm/store \
    pnpm install --frozen-lockfile --filter "@dom/web..."
COPY packages/ts ./packages/ts
COPY apps/web ./apps/web
RUN pnpm --filter @dom/web build

FROM nginxinc/nginx-unprivileged:1.29-alpine AS runtime
ENV NGINX_ENTRYPOINT_QUIET_LOGS=1
COPY --link --chmod=0644 apps/web/nginx.conf /etc/nginx/conf.d/default.conf
COPY --link --from=build /app/apps/web/dist /usr/share/nginx/html
EXPOSE 8080
LABEL org.opencontainers.image.title="dom-web" \
      org.opencontainers.image.description="墨屿 Web 前端（Vite 静态产物 + 同源反代）"
HEALTHCHECK --interval=15s --timeout=3s --start-period=5s --retries=5 \
    CMD wget -q -O /dev/null http://127.0.0.1:8080/healthz || exit 1