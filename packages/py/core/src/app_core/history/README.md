# History (app_core.history)

Owns version listing, named versions, and restore orchestration. A restore
materializes a historical Resource state, appends a new RESTORE journal marker,
and writes a new checkpoint; it never rewinds the existing journal.

`RestoreAtVersion.execute` accepts an optional progress callback. It reports
materialization, coalesced replay counts from `RestoreAtRevision`, and the save
stage. The maintenance `history.restore` task handler maps these snapshots to
the generic Task progress fields and checks cancellation at each reported
boundary.
