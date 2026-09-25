# Web Application

The web app composes routes and providers. Feature code lives under
`src/features/<feature>` and exports only public components and commands from
its `index.tsx` entrypoint.

## State and capability owners

- `src/shared/api` owns the singleton Client SDK and query client.
- TanStack Query owns server data; Zustand stores presentation state only.
- `packages/ts/resource-runtime` owns resource lifecycle and offline persistence.
- `packages/ts/realtime-client` owns the shared realtime connection and wire
  protocol; features receive stable resource IDs and typed events.
- `packages/ts/editor-core` owns Yjs and editor instances.

Features communicate through public exports, generated contracts, and stable
business IDs. A feature must not import another feature's implementation or
open its own network, permission, realtime, or offline-storage channel.
