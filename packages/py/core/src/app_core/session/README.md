# Session module

The session module owns framework-independent device session lifecycle and
quota policies. `domain/` defines session state, expiry, invalidation reasons,
and the deterministic two-device policy. `application/` and `ports/` are
reserved for use cases and adapter interfaces.
