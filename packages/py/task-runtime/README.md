# Async Task Runtime

The generic runtime owns handler registration, leases, execution retries,
cooperative cancellation, worker draining, and tracing seams. The Core Task
module owns the Task entity, canonical state transitions, use cases, and
persistence ports. Runtime execution code uses those Core types and remains
free of SQLAlchemy, FastAPI, and service imports.

Dependency direction is:

```text
workers -> task-runtime -> core.application
```

Core application orchestration owns Task state transitions and persistence
ports; infrastructure implements PostgreSQL repositories and the transactional outbox.
Handlers are resolved by task type and schema version before execution. Unknown
handlers and unsupported schemas are terminalized through fenced repository
operations rather than left Running.

`opentelemetry-api` is the tracing seam. Production exporter/SDK wiring is
intentionally outside this package; tests inject recording tracer fakes.

Attempt numbers are one-based per task. PostgreSQL serializes claims with a task
row lock and the `(task_id, attempt_number)` uniqueness constraint is the final
backstop. Execution epoch and current attempt ID fence all writes, including
task effects and terminal finishes.

The caller owns repository transactions and session lifetimes. `WorkerHost` can
receive an `execution_scope_factory` that yields a repository and registry
bound to one execution transaction. Handler writes, checkpoints, and successful
finish then commit together. If a handler raises, the scope exits and rolls back
before the runtime records retry or failure through its control repository.
Heartbeat and other control operations use that separate repository, so a long
handler does not occupy the session needed to renew its lease. Handler progress
is also written through the control repository in a short transaction; each
report checks cancellation before and after persisting its fenced snapshot. The
runtime does not open sessions or commit transactions itself.
