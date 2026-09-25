# Resource Runtime

`ResourceRuntime` owns the browser-side Resource cache. It stores opaque Yjs
state snapshots in IndexedDB, isolated by `(accountId, resourceId, replicaId)`;
the runtime does not import Yjs or decide how snapshots are merged.

## Offline open and local persistence

`openResource(accountId, resourceId)` hydrates the local cache before querying
the `ResourceGateway`. If the gateway fails because the browser is offline and
cached metadata exists, it returns that metadata and every stored snapshot with
`source: "offline-cache"`. The online result is also cached for future offline
opens. The caller must apply all `localSnapshots` through `editor-core` and
merge them with the server snapshot; `localUpdate` is only a compatibility
field when exactly one local snapshot exists.

`persistLocalState(accountId, resourceId, update, metadata)` writes an opaque
full-state byte snapshot. Each runtime instance gets a replica ID, so tabs do
not overwrite each other's last snapshot. `subscribeLocalUpdates` broadcasts
new snapshots between same-origin tabs for the same account and Resource. The
receiver still needs to merge the bytes with editor-core and persist the
resulting state.

Each returned snapshot exposes `revision`, `acceptedRevision`, and
`durableRevision`. Confirmation markers start at zero and survive later local
edits. `recordConfirmedRevisions` only advances markers monotonically for a
revision that already exists locally; callers must map actual server
acceptance and persistence receipts to that exact local revision before
calling it. It rejects receipts for future revisions. Online state and
WebSocket send success are not receipts.

The cached account ID is a local routing hint only. It is not a session or
permission proof. Reconnection and every remote write must revalidate session,
permission, and Resource lifecycle through the server.

## Disposal and deletion

`dispose()` closes this runtime's BroadcastChannel subscriptions. It never
deletes IndexedDB or local recovery data. `clearLocalResource` is a separate,
explicit destructive operation and requires
`{ confirmDiscardUnsyncedChanges: true }`; callers must only offer it after
warning that local unsynced work will be discarded. Browser storage eviction
remains controlled by the browser.

The runtime provides local persistence, cache hydration, and storage for
receipt-backed markers. It does not produce Synced or Durable evidence; those
states require generated realtime acceptance and durability receipts.
