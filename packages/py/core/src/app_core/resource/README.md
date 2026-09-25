# Resource Content (app_core.resource)

Owns Resource identity/metadata (arch 09 §30-32), the append-only content
journal (arch 06 §7-9, arch 29 §46-48), and checkpoints/revision (arch 06
§10-14). Depends on Permission-owned collab.resource_ownership/workspace
membership read-only for authorization; NEVER writes ownership rows.

Physical purge calls the Permission-owned cleanup port to remove resource
invitations, permissions, share links, and ownership bindings before deleting
Resource-owned rows. Comment threads are deleted by this module after comments.

Layout: domain (Resource/JournalOp/Checkpoint + errors), ports (resource/
journal/checkpoint repos + ReadOnlyResourceOwnershipPort + events), application
(CreateResource/AppendJournalOp/ReadJournal/ReadCurrentResourceContent/
CheckpointResource/RestoreAtRevision). ReadCurrentResourceContent returns the
latest durable projection with its checkpoint and journal boundaries after
checking Resource read access and Active lifecycle. RestoreAtRevision accepts an optional replay-progress
callback and coalesces updates to the start, each 100 replayed operations, and
the final operation. Task consumers: resource.checkpoint (workers/maintenance)
and history.restore (via app_core.history).
