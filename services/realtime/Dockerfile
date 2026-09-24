# Realtime gateway image (arch 15 §3): Node 22 + pnpm workspace.
FROM node:22-bookworm-slim AS builder
WORKDIR /app
RUN corepack enable
COPY package.json pnpm-lock.yaml pnpm-workspace.yaml ./
COPY packages/ts/realtime-client/package.json packages/ts/realtime-client/
COPY services/realtime/package.json services/realtime/
COPY packages/ts/contracts/package.json packages/ts/contracts/
RUN pnpm install --frozen-lockfile
COPY packages/ts/realtime-client/src packages/ts/realtime-client/src
COPY packages/ts/contracts/src packages/ts/contracts/src
COPY services/realtime/src services/realtime/src

FROM node:22-bookworm-slim
WORKDIR /app
ENV NODE_ENV=production
COPY --from=builder /app/node_modules node_modules
COPY --from=builder /app/packages node_modules/../../packages
COPY --from=builder /app/services/realtime services/realtime
COPY --from=builder /app/packages/ts/realtime-client packages/ts/realtime-client
COPY --from=builder /app/packages/ts/contracts packages/ts/contracts
EXPOSE 8765
WORKDIR /app/services/realtime
CMD ["node", "src/server/main.ts"]
