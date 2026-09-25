# ADR 0003: Durable Resource Session Recovery

- Status: Proposed
- Date: 2026-09-25
- Decision owner: Engineering Lead

## Context

The Architecture Constitution §§3 and 6 and Architecture 05/06 require a cold
Resource Session to restore a verified Checkpoint plus every later Durable
Journal update before becoming active. The browser now has IndexedDB-backed
local state, but Realtime catch-up is only a recent-update cache (50 updates,
one-hour TTL when Valkey is enabled) and has no authoritative Resource Y.Doc
or PostgreSQL Journal replay.

The existing Python `ReadJournal` use case and `read_cursor` repository can
read Journal pages, but no Realtime cold-start path calls them. The current
Checkpoint migration stores JSONB; the maintenance worker writes a marker
object rather than a verified Yjs binary checkpoint. The canonical data model
requires verified Checkpoint binary in S3. Existing marker rows cannot be used
as recovery state. Current Journal retention allows recovery from sequence 0
where the full Journal remains present.

## Proposed Decision

Implement the Resource Session and persistence modules reserved by Architecture
27 under `services/realtime/src/resource` and `services/realtime/src/persistence`.
Realtime will own one fenced Resource Session per Resource and restore it
before acknowledging a successful subscription:

1. Capture a stable Durable Watermark and select the latest verified
   Checkpoint at or before it. If none exists, replay from sequence 0 only
   while the complete Journal is retained.
2. Read Checkpoint metadata and binary from the canonical PostgreSQL metadata
   and S3 object storage, then read ordered Journal pages through the captured
   watermark using a read-only Realtime database role.
3. Verify checkpoint status, schema version, digest, Journal sequence
   continuity, ownership epoch, and durable boundary. Apply the checkpoint and
   Journal updates into a server Y.Doc. Activate the Session only after all
   checks pass; a gap, invalid checkpoint, or failed read leaves it inactive
   and preserves client-local unsynced content.
4. Once active, use the existing binary Yjs State Vector protocol for
   bidirectional reconciliation. The bounded Valkey backlog remains an
   acceleration layer only and never decides whether content is recoverable.
5. Replace the JSONB checkpoint marker with verified binary checkpoint
   creation and metadata matching Architecture 29. Do not compact Journal
   records until a verified Checkpoint covers them.

This proposal adds the PostgreSQL `pg` driver and an S3 client to the Realtime
service. It does not add a new service or change the selected PostgreSQL,
NATS, Yjs, or S3 products.

## Alternatives

1. **API-mediated Recovery Query.** The Resource API could read Checkpoint and
   Journal data and return pages to Realtime through a new registered internal
   Query. This avoids an S3 client in Realtime but adds service authentication,
   a cross-module contract, binary encoding/transfer, and another recovery
   dependency. Keep as the fallback if Realtime is not allowed direct
   read-only storage access.
2. **Keep the browser as recovery authority.** Rejected because a cold Realtime
   Session would remain empty, stale clients would not converge, and a missing
   or bounded browser cache could hide server data loss.
3. **Treat the current Checkpoint JSON marker as a base state.** Rejected
   because it contains no Yjs state and cannot reconstruct a Resource.
4. **Use only the bounded Valkey backlog.** Rejected because eviction, TTL, or
   more than 50 updates breaks the canonical recovery chain.

## Consequences

- Realtime gains the ResourceSession and persistence ownership already
  specified in Architecture 27 and can recover without a browser remaining
  online.
- Realtime requires narrowly scoped read access to Journal/checkpoint metadata
  and read-only S3 access to verified Checkpoint objects. Credentials and
  IAM/database grants must not permit Realtime to mutate Resource metadata or
  checkpoint objects.
- Checkpoint creation, verification, and compaction must align with the S3
  data model in Architecture 29. Until that rollout completes, old JSON marker
  rows are ignored as recovery checkpoints and full Journal replay is used.
- Recovery must be paginated to a fixed Durable Watermark, must detect missing
  sequences, and must expose load failure rather than silently activating an
  empty Session.
- The offline browser UI continues to distinguish Local, Synced, and Durable;
  session recovery does not make a WebSocket send or local IndexedDB write a
  Durable receipt.

## Migration

1. Add the read-only Realtime database role and S3 read capability, plus the
   two Realtime modules and cold-start state machine.
2. Add verified binary Checkpoint creation and metadata, preserving existing
   Journal rows until replacement Checkpoints have passed verification.
3. Deploy cold recovery in observe-only mode and compare restored Yjs state and
   watermarks against active sessions; then enable it for new Sessions.
4. Add crash/restart, no-checkpoint, checkpoint-plus-tail, paging, gap,
   ownership-fence, and backlog-overflow acceptance tests before enabling
   Journal compaction.

## Rollback

Disable cold Session activation through the new recovery adapter and retain
all Journal rows and old Checkpoint metadata. Do not delete or reinterpret
verified S3 Checkpoint objects during rollback. Existing clients retain their
local IndexedDB snapshots and the prior live-session path can be restored,
while the system reports cold recovery as unavailable until the adapter is
re-enabled.
