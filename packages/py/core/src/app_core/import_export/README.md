# Import / Export (`app_core.import_export`)

Owns Import and Export session identity, lifecycle, temporary object references,
and the authorized stable Resource export snapshot. The Resource module remains
the owner of Resource journal/checkpoint mutations; this module orchestrates
those use cases and the generic Task module.

Canonical docs: `docs/architecture/13-Import-Export-Design.md` (especially
§§7–10, 77–82, 91, 93, 96–99, 115), `docs/architecture/25-Async-Task-Execution-Design.md`
(§§8, 51–56, 68–76, 93), and `docs/architecture/29-PostgreSQL-Logical-Data-Model-Design.md`
(§§71–72, 97, 108–109).

Public interfaces are in `application/` and `ports/`. Allowed dependencies are
Resource read/write ports and use cases, Permission read authorization, Task
creation/runtime, and the AssetStore port for temporary objects. It does not
write Resource or Asset tables.

Owned tables: `work.import_sessions`, `work.export_sessions`. Temporary source
and result objects use the configured AssetStore under `tmp/import-export/`;
their UUIDs are session-scoped identities and are not user-visible Resource
Assets. No events are produced or consumed in this slice.

Tests: `packages/py/core/tests/import_export/`,
`packages/py/infrastructure/tests/postgres/import_export/`, and
`workers/maintenance/tests/test_import_export_handler.py`.
