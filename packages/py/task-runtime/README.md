# Async Task Runtime

The generic runtime owns task handler registration, leases, retries, cooperative
cancellation, worker draining, and tracing seams. It is framework-independent:
`task_runtime.domain` has no SQLAlchemy, FastAPI, or service imports.

Dependency direction is:

```text
workers -> task-runtime -> core.application
```

Core application orchestration owns task state transitions and persistence ports;
infrastructure implements PostgreSQL repositories and the transactional outbox.
Handlers are resolved by task type and schema version before execution. Unknown
handlers and unsupported schemas are terminalized through fenced repository
operations rather than left Running.

`opentelemetry-api` is the tracing seam. Production exporter/SDK wiring is
intentionally outside this package; tests inject recording tracer fakes.

Attempt numbers are one-based per task. PostgreSQL serializes claims with a task
row lock and the `(task_id, attempt_number)` uniqueness constraint is the final
backstop. Execution epoch and current attempt ID fence all writes, including
task effects and terminal finishes.
