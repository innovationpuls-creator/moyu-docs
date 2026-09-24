# Workspace Domain Module

Owns Workspace, Project, and Folder metadata lifecycle. `domain/` contains pure
lifecycle rules and validated values; `application/` coordinates use cases;
`ports/` defines metadata persistence boundaries implemented by infrastructure.

This slice exposes `CreateWorkspace` and a metadata-only `GetWorkspace` query.
Creation requires a persistent idempotency key bound to actor and request
fingerprint, checks Account-owned status (only `Active` may create), persists
metadata including the trusted actor as `created_by`, and grants the actor
initial ownership through Permission's
`GrantInitialWorkspaceOwner`. The Workspace idempotency port requires an atomic
unique-key claim; the PostgreSQL adapter must prove this under concurrency. Its
result includes that known initial owner only after the grant succeeds. The
GetWorkspace query authorizes through Permission before reading metadata, then
requires Permission's current-owner projection; it never fabricates ownership
from the creator. Workspace metadata carries lifecycle plus created/updated
timestamps so API projections match the generated contract.

Use cases do not begin or commit transactions. Workspace persistence, Permission
bootstrap, and idempotency storage must share the caller's AsyncSession; outer
rollback on integration failure is an infrastructure/API transaction guarantee
that still needs integration verification. Core unit tests do not claim atomic
rollback. The PostgreSQL adapter reuses `integration.idempotency_records` with a
`workspace:create:` internal namespace and stores the request fingerprint with
the replay response, keeping the caller's idempotency key stable while avoiding
cross-command key collisions. Create response `createdAt` is part of the persisted
Workspace metadata and the original idempotent result. Resource content lifecycle
and Purge are outside this module slice.

Project/Folder name availability follows the selected lifecycle rule: retained
Trashed, Purged, or Deleted rows continue reserving sibling names until physical
cleanup. Workspace duplicate-name scope remains undecided; no Workspace uniqueness
rule is implemented.

## Project and Folder Core Signatures

- `CreateProject.execute(actor_id, workspace_id, name, *, idempotency_key)` creates
  Workspace-scoped metadata after `Create` authorization and reserved-name check.
- `GetProjectTree.execute(actor_id, project_id)` authorizes `Read` and returns
  Workspace/Project metadata plus visible Folder metadata only.
- `RenameWorkspace.execute(actor_id, workspace_id, name, *, idempotency_key)` checks
  `Manage` authorization and updates only Workspace display metadata.
- `RenameProject.execute(actor_id, project_id, name, *, idempotency_key)` checks
  `Manage`, Active lifecycle, and Workspace sibling name reservations.
- `ArchiveProject`, `UnarchiveProject`, `TrashProject`, and `RestoreProject` expose
  `execute(actor_id, project_id, *, idempotency_key)` and change only Project state.
- `CreateFolder.execute(actor_id, project_id, parent_folder_id, name, *,
  idempotency_key)` supports root (`None`) or same-Project Folder parent.
- `RenameFolder.execute(actor_id, folder_id, name, *, idempotency_key)` and
  `MoveFolder.execute(actor_id, folder_id, destination_parent_folder_id, *,
  idempotency_key)` preserve Folder identity; Move validates application-supplied or
  repository-provided descendant state for cycles and same-Project membership.
- `TrashFolder` and `RestoreFolder` expose
  `execute(actor_id, folder_id, *, idempotency_key)`. Effective descendant
  lifecycle is computed from the ancestor chain; descendants are not rewritten.

All mutating use cases consume `MutationIdempotencyPort`; infrastructure owns its
atomic claim/replay semantics. Pagination cursors, Resource rows/content, Purge,
physical cleanup, transactional tree rechecks, and lifecycle events are deferred
to their owning integrations. Core use cases do not commit transactions.

Canonical owner: `docs/architecture/09-Workspace-Project-Resource-Lifecycle-Design.md`.
