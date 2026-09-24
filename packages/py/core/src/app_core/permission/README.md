# Permission Domain Module

Owns Workspace membership authority and server-side Workspace authorization.

- `domain/`: Owner/Member membership model, transfer result, and pure inheritance policy
- `application/`: initial Owner grant, authorized Owner transfer, and sole-owner query orchestration
- `ports/`: membership repository and authorization interfaces implemented outside core

Canonical documents: `docs/architecture/07-Permission-Access-Control-Design.md`, `docs/architecture/29-PostgreSQL-Logical-Data-Model-Design.md`, and ADR `docs/adr/0001-workspace-membership-owner-kind.md`.

The module owns writes to Permission membership state only. Repository operations participate in caller-managed transactions; application code does not open or commit transactions. Owner transfer is one atomic repository operation: its implementation serializes the idempotency key, authoritative current-Owner and active-target checks, membership mutation, and stored replay result in the same transaction. Application code does not repeat Owner authorization through the access port. Infrastructure failures propagate without fallback. Auth consumes the existing `WorkspaceOwnershipQueryPort` shape `(bool, workspace_name)`.

Workspace Owner inherits Project `Manage` within the same Workspace at authorization evaluation time. Transfer keeps the previous Owner as a Member and does not mutate independent Project memberships.

Unit tests: `packages/py/core/tests/permission/test_workspace_ownership.py`.
