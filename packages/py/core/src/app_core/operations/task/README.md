# Task Operations

Owns the generic Task entity, canonical state and priority values, task creation,
query, cancellation, retry orchestration, and Task persistence ports. The Task
Runtime owns worker execution, attempts, leases, retries, cancellation
checkpoints, and recovery mechanics; it depends on this module's domain types.

Canonical owners: `docs/architecture/25-Async-Task-Execution-Design.md` and
`docs/architecture/27-Repository-Module-Layout-Design.md`.

The module follows `domain/`, `application/`, and `ports/` boundaries. Domain
code has no runtime or infrastructure imports. PostgreSQL implementations live
in `packages/py/infrastructure/src/app_infra/postgres/task/`.

Tests: `packages/py/core/tests/operations/task/`.
