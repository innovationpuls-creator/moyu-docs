# Maintenance Worker

The maintenance runner assembles registered Task handlers over caller-owned
execution transactions. Task control operations, including progress snapshots,
use separate short transactions so leases and visible Task state remain
available while a handler runs.

`webhook.deliver` loads its subscription through a short-lived session factory.
The runner releases the handler's execution transaction before outbound HTTP
and starts a new transaction after the request returns so terminal task state
can commit normally. Other database-only handlers keep their execution writes
atomic with successful Task completion.
