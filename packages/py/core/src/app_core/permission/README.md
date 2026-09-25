# Permission Domain Module

Owns Workspace membership authority and server-side Workspace authorization.

- `domain/`: Owner/Member membership model, transfer result, and pure inheritance policy
- `application/`: initial Owner grant, authorized Owner transfer, and sole-owner query orchestration
- `ports/`: membership repository and authorization interfaces implemented outside core

Canonical documents: `docs/architecture/07-Permission-Access-Control-Design.md`, `docs/architecture/29-PostgreSQL-Logical-Data-Model-Design.md`, and ADR `docs/adr/0001-workspace-membership-owner-kind.md`.

The module owns writes to Permission membership state only. Repository operations participate in caller-managed transactions; application code does not open or commit transactions. Owner transfer is one atomic repository operation: its implementation serializes the idempotency key, authoritative current-Owner and active-target checks, membership mutation, and stored replay result in the same transaction. Application code does not repeat Owner authorization through the access port. Infrastructure failures propagate without fallback. Auth consumes the existing `WorkspaceOwnershipQueryPort` shape `(bool, workspace_name)`.

Workspace Owner inherits Project `Manage` within the same Workspace at authorization evaluation time. Transfer keeps the previous Owner as a Member and does not mutate independent Project memberships.

Unit tests: `packages/py/core/tests/permission/test_workspace_ownership.py`.

## Share Links

`ShareLinkAdministration` owns Resource Share Link creation, listing, status, expiry, revocation, regeneration, and anonymous token resolution. Owner and Manage authorization is enforced by the repository against the Resource's current Workspace, Project, and Resource permissions.

Anonymous grants are limited to Resource Content Read. They do not grant write, comment, or realtime presence capabilities. Expiry is evaluated during resolution and status reads; revocation is persisted and immediately denies resolution.

Share tokens are generated in the application layer and only their SHA-256 hashes are written to `core.share_links`. The relative URL is returned only from an authorized create/regenerate result; idempotent replay material is encrypted at rest with AES-GCM. List, status, and audit results do not contain the token or URL.

Focused tests: `packages/py/core/tests/permission/test_share_links.py` and `packages/py/infrastructure/tests/postgres/test_share_link_repository.py`.
