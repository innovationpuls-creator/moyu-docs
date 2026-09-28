# syntax=docker/dockerfile:1
# DOM realtime WebSocket gateway 镜像（doc 26 §55：OCI Image / 多阶段 / 非 root）。
# workspace 包（@dom/contracts、@dom/realtime-protocol）的 exports 直接指向 TS
# 源码，无需预构建；运行时由 tsx 直接执行。
FROM node:24-bookworm-slim AS build
WORKDIR /app
# npm registry 可覆盖（国内部署可传 npmmirror；非敏感值，落层可接受）。
ARG NPM_REGISTRY=https://registry.npmjs.org/
ENV npm_config_registry=${NPM_REGISTRY}
RUN corepack enable
# 先复制 lock 与各 workspace 包 manifest，最大化依赖层缓存命中。
COPY package.json pnpm-workspace.yaml pnpm-lock.yaml ./
COPY packages/ts/contracts/package.json packages/ts/contracts/package.json
COPY packages/ts/realtime-protocol/package.json packages/ts/realtime-protocol/package.json
COPY services/realtime/package.json services/realtime/package.json
RUN --mount=type=cache,target=/root/.local/share/pnpm/store \
    pnpm install --frozen-lockfile --filter "@dom/realtime..."
COPY packages/ts/contracts ./packages/ts/contracts
COPY packages/ts/realtime-protocol ./packages/ts/realtime-protocol
COPY services/realtime ./services/realtime

FROM node:24-bookworm-slim AS runtime
ENV NODE_ENV=production
WORKDIR /app
COPY --link --from=build --chown=1000:1000 /app/node_modules /app/node_modules
COPY --link --from=build --chown=1000:1000 /app/packages/ts/contracts /app/packages/ts/contracts
COPY --link --from=build --chown=1000:1000 /app/packages/ts/realtime-protocol /app/packages/ts/realtime-protocol
COPY --link --from=build --chown=1000:1000 /app/services/realtime /app/services/realtime
USER node
WORKDIR /app/services/realtime
EXPOSE 8765
LABEL org.opencontainers.image.title="dom-realtime" \
      org.opencontainers.image.description="墨屿 WebSocket 实时协同网关"
HEALTHCHECK --interval=15s --timeout=3s --start-period=15s --retries=5 \
    CMD node -e "fetch('http://127.0.0.1:8765/').then(r => process.exit(r.ok ? 0 : 1)).catch(() => process.exit(1))"
CMD ["node", "--import=tsx", "src/server/main.ts"]