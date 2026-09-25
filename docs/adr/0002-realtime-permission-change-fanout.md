# ADR 0002: Realtime Permission Change Fanout

- Status: Proposed
- Date: 2026-09-25
- Decision owner: Engineering Lead

## Context

The Architecture Constitution §3 requires permission changes to affect active
Realtime collaboration without a page refresh. Permission writes already add
`PermissionChanged` facts to `integration.outbox_events`, and the event is
registered as `event.permission.changed.v1`. No relay currently publishes
those rows to Realtime; Realtime only subscribes to `rt.broadcast.>`.

Realtime authorizes a subscription when it starts and rechecks edit capability
for incoming Yjs updates. Its local subscription index does not currently
retain the account ID needed to target permission revalidation. Removing Read
must also clear that instance's Awareness and Presence state.

## Proposed Decision

Use the existing PostgreSQL transactional outbox and NATS JetStream to deliver
permission changes to every Realtime instance:

1. A generic outbox relay claims committed unpublished rows, publishes the
   registered Event Envelope to a durable JetStream stream, and only then
   marks the row published. `eventId` is the deduplication key; consumers must
   remain idempotent because delivery is at least once.
2. Every Realtime instance has its own stable durable consumer. Instances must
   not share a queue group or durable consumer, which would deliver each event
   to only one instance.
3. Realtime stores the authenticated `accountId` on each local Resource
   subscription. When a permission event arrives, it temporarily gates output
   for that account's subscriptions, rechecks current server capabilities, and
   then either removes subscriptions without Read or retains read-only
   subscriptions while rejecting writes. It clears Awareness and Presence
   wherever Read was lost, then acknowledges the event.
4. An event without `accountId` triggers revalidation of all local Resource
   subscriptions. Event payloads are hints for revalidation; Realtime never
   trusts the event's role field as an authorization decision.
5. Session replacement continues through the existing Session invalidation
   path and closes the connection; permission loss does not invalidate the
   entire Session.

## Alternatives

1. **NATS Core pub/sub.** Rejected because an instance disconnected during
   publication permanently misses the invalidation.
2. **One shared JetStream consumer group.** Rejected because JetStream would
   distribute each event to one instance instead of every instance holding
   affected connections.
3. **Reauthorize only incoming edits.** Rejected because a downgraded or
   removed member could continue receiving document and Awareness data.

## Consequences

- Permission events reach all healthy instances and can be replayed after a
  temporary consumer outage.
- Duplicate delivery and slow consumer handling are expected. Revalidation,
  unsubscribe, Presence cleanup, and event acknowledgement must be idempotent.
- The system needs durable stream configuration, stable instance consumer
  identities, lag monitoring, retry/dead-letter handling, and safe cleanup of
  retired consumers.
- Delivery remains asynchronous between the permission transaction commit and
  each Realtime consumer. The production propagation deadline and behavior if
  it is exceeded must be defined before claiming strict immediate revocation.
  A cross-instance revocation barrier would trade permission-command
  availability for a stronger no-post-commit-delivery guarantee and is not
  included in this proposal.

## Migration

1. Normalize all effective membership/role changes and Owner transfer to the
   registered `PermissionChanged` Event Envelope and subject. Do not publish
   this event for invitation creation/revocation, which does not change an
   effective permission.
2. Add the outbox relay and a dedicated JetStream stream without changing the
   existing Realtime content broadcast subject.
3. Add account identity to the local subscription index, output gating during
   revalidation, and authorization/Presence integration coverage.
4. Enable consumers before relying on fanout; keep the existing
   per-write authorization check throughout rollout.

## Rollback

Disable the relay and JetStream consumers while keeping server-side
authorization on every incoming write. Do not remove outbox rows during
rollback. If any Realtime instance cannot establish the permission consumer,
it must not claim that active permission revocation is operating normally.
