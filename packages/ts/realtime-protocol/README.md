# Realtime Protocol

This package owns the shared binary frame codec used by the browser realtime
client and the Realtime service. Frame headers use the generated
`@dom/contracts` types, so encoded frames carry the contract-defined
`frameType` and `payloadKind` fields.

The package only encodes and decodes versioned sync frames. WebSocket lifecycle,
authentication, authorization, subscriptions, and Yjs document state remain in
their owning client and service modules.

Run `pnpm --filter @dom/realtime-protocol test` and
`pnpm --filter @dom/realtime-protocol typecheck` to validate the codec.
