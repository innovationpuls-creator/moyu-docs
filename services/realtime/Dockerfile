ARG NODE_IMAGE=node:24-bookworm-slim@sha256:0e0ff40c39bc087845bfb27465a0df4ea419520094bc35842ff83dd8cbe6f9b6
FROM ${NODE_IMAGE} AS builder
ARG NPM_REGISTRY=https://registry.npmjs.org
WORKDIR /app
ENV COREPACK_NPM_REGISTRY=${NPM_REGISTRY} \
    npm_config_registry=${NPM_REGISTRY}
RUN corepack enable
COPY . .
RUN pnpm install --frozen-lockfile --filter @dom/realtime... \
    && pnpm install --frozen-lockfile --prod --filter @dom/realtime...

FROM ${NODE_IMAGE} AS runtime
ENV NODE_ENV=production
WORKDIR /app
COPY --from=builder --chown=node:node /app/node_modules /app/node_modules
COPY --from=builder --chown=node:node /app/services/realtime /app/services/realtime
COPY --from=builder --chown=node:node /app/packages/ts/contracts /app/packages/ts/contracts
COPY --from=builder --chown=node:node /app/packages/ts/realtime-protocol /app/packages/ts/realtime-protocol
USER node
WORKDIR /app/services/realtime
EXPOSE 8765
HEALTHCHECK --interval=15s --timeout=3s --start-period=15s --retries=5 \
    CMD node -e "fetch('http://127.0.0.1:8765/').then(r => process.exit(r.ok ? 0 : 1)).catch(() => process.exit(1))"
CMD ["node", "--import=tsx", "src/server/main.ts"]
