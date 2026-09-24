# Resource Content (app_core.resource)

Owns Resource identity/metadata (arch 09 §30-32), the append-only content
journal (arch 06 §7-9, arch 29 §46-48), and checkpoints/revision (arch 06
§10-14). Depends on Permission-owned collab.resource_ownership/workspace
membership read-only for authorization; NEVER writes ownership rows.

Layout: domain (Resource/JournalOp/Checkpoint + errors), ports (resource/
journal/checkpoint repos + ReadOnlyResourceOwnershipPort + events), application
(CreateResource/AppendJournalOp/ReadJournal/CheckpointResource/
RestoreAtRevision). Task consumers: resource.checkpoint (workers/maintenance).
