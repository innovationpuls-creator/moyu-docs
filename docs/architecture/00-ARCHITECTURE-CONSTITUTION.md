# Architecture Constitution

> Status: Normative
>
> Scope: `01` to `29` architecture design set
>
> Rule: Local AI should read this file first, then load the Canonical Owner document for the task and only its direct dependencies. Do not load all design files by default.

## 1. Conflict Resolution Order

When documents appear to conflict, use this order:

```text
1. Architecture Constitution
2. Canonical Owner Document
3. Specialized Subordinate Design
4. Example / Scenario / Recommendation
```

`PRODUCT_DECISION_PENDING` is not permission to guess. Stop that product branch and ask for a decision while continuing unrelated engineering work.

A later example never overrides a Canonical Owner rule.

---

## 2. Canonical Owners

| Concept | Canonical Owner |
| --- | --- |
| Document Block / Node model | `01-Block-Design.md` |
| nodeId / NodeRef identity | `02-Node-Identity-Design.md` |
| Resource collaboration boundary | `03-Resource-Collaboration-Design.md` |
| Command / Query / Event / Stream semantics, top-level errors, request identity | `04-Unified-Module-Communication-Design.md` |
| WebSocket / Yjs Sync / Awareness / sync receipts | `05-Realtime-Collaboration-Protocol-Design.md` |
| Journal / Checkpoint / Compaction / durability | `06-Persistence-Design.md` |
| Roles / Capabilities / Share / authorization | `07-Permission-Access-Control-Design.md` |
| History / Version / Restore | `08-History-Version-Restore-Design.md` |
| Workspace / Project / Folder / Resource lifecycle | `09-Workspace-Project-Resource-Lifecycle-Design.md` |
| Asset / Binary storage | `10-Asset-File-Storage-Design.md` |
| Search / Index | `11-Search-Index-Design.md` |
| AI Task domain / ChangeSet | `12-AI-Task-ChangeSet-Design.md` |
| Import / Export | `13-Import-Export-Design.md` |
| Observability / Operations | `14-Observability-Operations-Design.md` |
| Deployment / Scaling / DR | `15-Deployment-Scaling-Disaster-Recovery-Design.md` |
| Account / Auth / Session | `16-Account-Auth-Session-Design.md` |
| Comment / Mention / Notification | `17-Comment-Mention-Notification-Design.md` |
| Client Runtime / Offline / Multi-tab integration | `18-Client-API-Frontend-Integration-Design.md` |
| Frontend feature contract inventory | `19-Frontend-Module-Contract-Design.md` |
| Gateway / OAuth Callback / Webhook / Email / external providers | `20-API-Gateway-External-Integration-Design.md` |
| Security / Privacy / Threat Model | `21-Security-Privacy-Threat-Model-Design.md` |
| Client-server feedback state semantics | `22-Client-Server-Interaction-Feedback-Flow-Design.md` |
| Application logs / diagnostics / correlation | `23-Application-Logging-Diagnostics-Design.md` |
| Test / Quality / Release gates | `24-Testing-Quality-Release-Design.md` |
| Async Task / Attempt / Lease / Retry / Worker recovery | `25-Async-Task-Execution-Design.md` |
| Technology stack / runtime / infrastructure products | `26-Technology-Stack-Decision.md` |
| Repository layout / module dependency direction | `27-Repository-Module-Layout-Design.md` |
| Machine-readable Contract / Schema Registry | `28-Contract-Schema-Registry-Design.md` |
| PostgreSQL logical data model / transaction boundaries | `29-PostgreSQL-Logical-Data-Model-Design.md` |

`25-Async-Task-Execution-Design.md` owns generic Task execution semantics. Domain documents may only add subtype-specific stages and results; they must not redefine Task identity, Attempt, Lease, Retry, Cancel, Worker recovery or Queue reliability.

---

## 3. System Invariants

1. `Resource` is the unique realtime collaboration boundary.
2. `Project` and `Folder` organize Resources; they are not Yjs collaboration rooms.
3. Every Resource has a stable `resourceId`; rename, move, archive and restore do not change it.
4. Document realtime content uses one `Y.Doc` as the collaboration Source of Truth.
5. The system must not maintain a second mutable Block Tree beside Editor/Yjs state.
6. `Block` is a semantic kind of Node, not a DOM element and not every Node.
7. Stable addressable node identity is `nodeId`.
8. Cross-module node references use `NodeRef = resourceId + nodeId`.
9. Text-range references use `NodeRef + Y.RelativePosition`; absolute offsets and DOM paths are not durable identities.
10. Create / duplicate / cross-document paste creates new logical node identity; ordinary edit and move preserve identity; Undo restores original identity.
11. Document Command is stateless intent-to-Editor-Transaction translation and does not own document state.
12. Human, AI, plugin, import and formatter writes must converge into the same formal Resource mutation path; no side database copy of current document content.
13. System communication semantics are `Command / Query / Event / Stream`; transport choice is separate.
14. Query has no business side effects.
15. Event states a fact that already happened and must be versionable.
16. `requestId` identifies one concrete request / attempt; it is not the idempotency identity.
17. Retry-safe Mutating Commands use a stable `idempotencyKey`; a retry may have a new `requestId`.
18. Long work uses stable `taskId`; each physical execution uses a distinct `attemptId`. PostgreSQL Task State is authoritative, Queue is only an execution trigger, and stale Attempts must be fenced after ownership transfer.
19. Top-level Error Category is canonical: `Validation / Authentication / Permission / NotFound / Conflict / RateLimit / Timeout / DependencyFailure / Unavailable / Internal`.
20. Domain-specific error logic uses stable `errorCode`; clients do not branch on human message text.
21. Realtime content synchronization uses Yjs binary protocol; do not Base64-wrap Yjs updates into ordinary business JSON as the primary path.
22. Awareness is ephemeral Presence/Cursor/Selection state and is never persisted as Resource content.
23. User input is Local-first and must not wait for network, PostgreSQL, Journal, Checkpoint or Search.
24. Realtime state semantics are distinct: `Local != Synced != Durable`.
25. `Synced` requires a server acceptance boundary; `Durable` requires a persistence-confirmed durable boundary. Socket send success is neither.
26. Sync/Durable receipts are batchable watermarks or equivalent boundaries, not per-keystroke business ACKs.
27. Persistence is `Durable Update Journal + Checkpoint + Compaction`.
28. Checkpoint is a recovery accelerator and compaction boundary, not the user-visible History version model.
29. Safe Resource Session release requires relevant accepted updates to be Durable; it does not require an immediate Checkpoint.
30. Cold recovery is `latest verified Checkpoint + later Durable Journal + client State Vector reconciliation`.
31. Different Resources may execute in parallel; one Resource must not require a global system serialization point.
32. Resource ownership transfer must have stale-owner fencing. After a new ownership epoch becomes valid, an old owner cannot continue authoritative writes or advance Durable Boundary.
33. PostgreSQL is the authoritative production database for business metadata, auth/session, permission, lifecycle, comments, tasks and related control-plane state.
34. Large binary Asset data does not live in PostgreSQL or Y.Doc; it lives in private Object Storage behind stable `assetId` references.
35. Search, vector index, cache, preview and other derived systems are rebuildable and never Source of Truth.
36. Auth answers “who are you”; Permission answers “what can you do”. They must remain separate.
37. All security-critical authorization is enforced server-side; UI capability state is never a security boundary.
38. Share Link may grant only its explicit capabilities. Current confirmed first-version rule is anonymous read, no anonymous edit, no anonymous comment.
39. Permission changes must affect active Realtime collaboration without requiring page refresh.
40. AI is a constrained Actor, not a superuser. AI writes first become `ChangeSet`, then pass validation / permission / current-state checks and the normal Resource write path.
41. Prompt content, imported data, search results and comments are untrusted input and cannot expand AI Tool Scope or Permission.
42. Import / Export and Asset parsers treat all external files as untrusted; archive traversal, bomb, active content and malware boundaries are mandatory.
43. Gateway validates edge concerns and routes requests; Domain Logic remains in Domain modules.
44. External Provider failures must degrade only the affected capability and must not cascade into Resource / Realtime / Permission / Persistence correctness.
45. Official frontend accesses backend capabilities through Client Contract / Client SDK, not internal service APIs.
46. Stream is for realtime feedback, not the only Source of Truth. Query / Sync must recover current state after reconnect or missed events.
47. Frontend `Server State / Local UI State / Realtime State / Editor State / Offline State` are separate ownership categories.
48. Already-opened cached Resources may edit offline; reconnect must revalidate Session, Permission and Lifecycle before remote writes.
49. Unsynced local user content must never be silently discarded because of logout, session replacement, permission downgrade or Resource lifecycle changes.
50. Application Log, Trace, Metric, Audit and Client Telemetry are distinct systems with distinct retention and access semantics.
51. Passwords, tokens, secrets, signed URLs and full sensitive content are excluded from normal logs.
52. Security-sensitive actions, Owner/Permission changes, Permanent Purge, sensitive Export and Break Glass actions require Audit.
53. Production services are multi-instance capable; correctness must not depend on one process's memory or local disk.
54. Cache is disposable optimization, not permission truth or business truth.
55. Database and Resource schema evolution must support mixed-version rollout and explicit compatibility testing.
56. Old persisted Yjs / Checkpoint fixtures must remain part of migration tests so nodeId, NodeRef, RelativePosition, Comment Anchor and recovery-chain semantics cannot silently drift.
57. Release gates include Static Check, Unit, Contract, Integration and targeted security/migration tests; high-risk modules require stronger gates and staged rollout.
58. A failed auxiliary system must not falsely report success for the primary business operation it did not complete.
59. One Account may have at most 2 active device Sessions. Tabs inside one browser Session do not consume additional device slots; when a new device login would exceed the limit, the oldest active device Session is replaced and must lose API / Realtime authority promptly.
60. No architecture example, test fixture or UI design may create a second source of truth that contradicts its Canonical Owner.
61. Production implementation stack is fixed by `26`; core Realtime Transport is `WebSocket/WSS`, with Yjs binary payloads carried directly over the WebSocket protocol.
62. First-stage physical architecture is Modular Monolith API + Dedicated Realtime Service + Worker Pools; Domain modules are not automatically network microservices.
63. Repository and dependency direction are fixed by `27`; Domain code does not depend directly on Framework / Infrastructure implementations.
64. Cross-module machine contracts must be registered in `28`; hand-written TypeScript/Python DTO duplication is not a Source of Truth.
65. PostgreSQL logical ownership, constraints and transaction boundaries are fixed by `29`; every table has one Domain Owner.

---

## 4. Canonical Lifecycle Vocabulary

```text
ArchiveProject    → ProjectArchived
UnarchiveProject  → ProjectUnarchived
TrashProject      → ProjectTrashed
RestoreProject    → ProjectRestored
PurgeProject      → ProjectPurged

TrashResource     → ResourceTrashed
RestoreResource   → ResourceRestored
PurgeResource     → ResourcePurged

RestoreVersion    → HistoryRestored
ApplyChangeSet    → ChangeSetApplied
AITaskCompleted   → completed AI task event
```

Use `Delete` only as natural-language explanation when the exact lifecycle state is irrelevant. Stable Contract names use `Trash / Restore / Purge`.

---

## 5. Confirmed Product Policies

The following product decisions are normative and no longer pending:

```text
Active device Sessions per Account <= 2
Desktop Web = full experience
Mobile = companion read/comment/notification experience
Third device login = replace the oldest active device Session
Archived Project = read-only
Archived Project = excluded from default Global Search, available through Archived filter
Ordinary History = Edit / Manage / Owner
Trash / Restore = Manage / Owner
Purge = Owner only
PendingVerification email account = may enter product, may not create Workspace
Provider-only WeChat / Feishu account = Active, prompt for Recovery Email
Account Delete Grace Period = 30 days, cancellable before final deletion
Anonymous Share = read-only Resource content, no internal Comment Thread, no Presence
Comment Thread = flat replies
Resolve / Reopen = Thread Creator or Edit / Manage / Owner
Resolved Thread = must Reopen before Reply
Comment Content = lightweight Rich Text: Bold / Italic / Code / Link / Mention
```

---

## 6. Local AI Loading Rule

For implementation tasks:

```text
Always load:
  00-ARCHITECTURE-CONSTITUTION.md

Then load:
  the Canonical Owner document
  + direct dependency documents named by that owner

Do not load:
  all 01-29 documents by default
```

If a requested implementation contradicts this Constitution, report the contradiction before editing code.
