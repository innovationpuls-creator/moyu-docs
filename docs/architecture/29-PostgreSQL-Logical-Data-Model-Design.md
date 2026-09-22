# PostgreSQL Logical Data Model Design

> Status: Normative
>
> Canonical Owner: PostgreSQL logical entities, ownership, constraints and transaction boundaries
>
> Note: 本文件定义逻辑模型，不替代 Alembic Migration。DDL 由实现根据本文件生成。

## 1. 目标

本设计把此前分散在 Auth、Workspace、Resource、Permission、History、Comment、Task、Asset、AI、Import / Export、Webhook、Audit、Persistence 中的 PostgreSQL 需求收成一套逻辑模型。

本文件回答：

```text
哪些数据属于 PostgreSQL
实体之间怎么关联
哪些约束必须由数据库保证
哪些表由哪个 Domain 拥有
哪些操作必须同一事务
哪些数据不能放 JSONB 偷懒
哪些表需要 Partition / Retention
```

---

# Part A: Database Topology

## 2. 一个主业务数据库

第一阶段：

```text
one logical PostgreSQL cluster
one primary business database
```

不做：

```text
database per workspace
database per domain
database per microservice
```

---

## 3. Logical Schemas

正式划分：

```text
auth
core
collab
work
integration
audit
```

---

## 4. Schema Meaning

```text
auth        → Account / Identity / Session
core        → Workspace / Project / Folder / Resource / Permission / Asset metadata
collab      → Realtime ownership / Journal / Checkpoint / History / Comment / Notification
work        → Task / Attempt / ChangeSet / Import / Export / Search coordination
integration → Outbox / Inbox / Webhook / Provider delivery
audit       → Audit Entry
```

---

# Part B: Common Conventions

## 5. Primary Key

跨模块业务实体：

```text
UUIDv7
```

PostgreSQL 类型：

```text
uuid
```

---

## 6. Time

统一：

```text
TIMESTAMPTZ
UTC
```

---

## 7. Lifecycle

复杂实体使用显式：

```text
status / lifecycle
```

不能只用 `deleted_at != null` 代替完整生命周期。

---

## 8. JSONB

允许用于：

```text
small extensible metadata
safe target reference
immutable diagnostic metadata
domain-specific bounded payload
```

禁止用 JSONB 代替：

```text
membership
permission
foreign key
session
task state
resource relationship
```

---

## 9. Binary

大型 Binary 进入 S3-compatible Object Storage。

PostgreSQL 仅保存：

```text
object_key
hash
size
mime
metadata
```

例外：小型 Yjs Journal Update 可以保存为 `BYTEA`，这是 Persistence Canonical Design 的正式一部分。

---

# Part C: Account

## 10. auth.accounts

关键字段：

```text
account_id uuid PK
status
primary_email nullable
normalized_email nullable
email_verified_at nullable
auth_epoch bigint
created_at
updated_at
```

---

## 11. Account Status

```text
PendingVerification
Active
Disabled
DeletionPending
Deleted
```

Provider-only 微信 / 飞书账号可直接 Active。

---

## 12. Email

Email 不是 Account Primary Key。

`normalized_email` 用于唯一性 / lookup，原始邮箱值用于显示。

---

# Part D: Identity

## 13. auth.identities

```text
identity_id
account_id FK
provider
provider_subject
provider_email nullable
created_at
last_used_at
```

---

## 14. Identity Unique

数据库硬约束：

```text
UNIQUE(provider, provider_subject)
```

禁止同一个微信 / 飞书主体绑定多个 Account。

---

## 15. Email Identity

邮箱登录也进入统一 Identity 模型，不让 `accounts.primary_email` 独自承担全部身份语义。

---

# Part E: Password / One-time Token

## 16. auth.password_credentials

```text
account_id PK/FK
password_hash
algorithm_version
password_changed_at
```

只保存成熟 Password Hash。

---

## 17. auth.one_time_tokens

用于：

```text
email verification
password reset
sensitive flow confirmation
```

逻辑字段：

```text
token_id
account_id nullable
token_type
token_hash
expires_at
consumed_at nullable
created_at
```

数据库只保存 token hash，不保存可直接使用的明文 Token。

---

# Part F: Session

## 18. auth.sessions

```text
session_id
account_id
device_id
status
session_version
created_at
last_seen_at
expires_at
replaced_at nullable
replaced_by_session_id nullable
```

---

## 19. Session Status

```text
Active
Replaced
Expired
Revoked
```

---

## 20. Device Session

同一浏览器多个 Tab 共用一个 Device Session。

`device_id` 只是产品会话设备标识，不是可信硬件证明。

---

## 21. 最多 2 个 Active Device Sessions

登录事务：

```text
lock account row
↓
create / activate new session
↓
load active device sessions oldest first
↓
if active > 2:
  mark oldest Replaced
↓
write SessionReplaced outbox event
↓
commit
```

必须在数据库事务中可靠保证产品规则，不能只在应用层先 Count 再 Insert。

---

# Part G: Account Deletion

## 22. auth.account_deletion_requests

```text
account_id
state
requested_at
execute_after
cancelled_at nullable
completed_at nullable
```

当前：

```text
execute_after = requested_at + 30 days
```

---

# Part H: Workspace

## 23. core.workspaces

```text
workspace_id
name
status
created_by
created_at
updated_at
deletion_requested_at nullable
```

---

## 24. Workspace Status

```text
Active
DeletionPending
Deleted
```

---

# Part I: Workspace Membership

## 25. core.workspace_members

```text
workspace_id
account_id
membership_kind
created_at
```

Primary Key：

```text
(workspace_id, account_id)
```

Workspace Membership 不等于 Project / Resource Role。

---

# Part J: Project

## 26. core.projects

```text
project_id
workspace_id
name
normalized_name
lifecycle
created_by
created_at
updated_at
archived_at nullable
trashed_at nullable
```

---

## 27. Project Lifecycle

```text
Active
Archived
Trashed
Purging
Purged
```

Confirmed Product Rule：

```text
Archived = read-only
Archived = excluded from default Global Search
```

---

# Part K: Folder

## 28. core.folders

```text
folder_id
project_id
parent_folder_id nullable
name
normalized_name
lifecycle
created_at
updated_at
```

---

## 29. Folder Tree

FK：

```text
parent_folder_id → core.folders.folder_id
```

必须保证：

```text
same project
no cycle
```

Cycle 防护由 Application Validation + Transactional Check 实现。

---

# Part L: Resource

## 30. core.resources

```text
resource_id
project_id
folder_id nullable
resource_type
name
normalized_name
lifecycle
schema_version
created_by
created_at
updated_at
trashed_at nullable
```

---

## 31. Resource Lifecycle

```text
Active
Trashed
Purging
Purged
```

第一版 Resource 没有独立 Archive。

---

## 32. Resource Type

初始：

```text
document
code
markdown
text
```

`resource_type` 不允许普通 Update 改类型。

Convert：

```text
new Resource
```

---

# Part M: Name Conflict

## 33. Sibling Name

显示名保留原始 Unicode。

额外保存：

```text
normalized_name
```

用于同级冲突检测。

Name 不是 Identity。

---

# Part N: Project Access

## 34. core.project_members

```text
project_id
account_id
role
membership_kind
created_at
updated_at
```

Unique：

```text
(project_id, account_id)
```

---

## 35. Role

```text
Owner
Manage
Edit
Comment
Read
```

Project 必须保持至少一个 Owner。

Owner Transfer 必须同一事务完成。

---

# Part O: Resource Override

## 36. core.resource_permissions

只保存 Custom Resource Permission：

```text
resource_id
account_id
role
created_at
updated_at
```

Unique：

```text
(resource_id, account_id)
```

没有 Override 时继承 Project Role，不复制 inherited rows。

---

# Part P: Invitation

## 37. core.invitations

```text
invitation_id
workspace_id
project_id nullable
resource_id nullable
target_email nullable
target_account_id nullable
role
state
token_hash
expires_at
created_by
created_at
accepted_at nullable
```

---

## 38. Invite State

```text
Pending
Accepted
Expired
Revoked
```

---

# Part Q: Share Link

## 39. core.share_links

```text
share_id
resource_id
token_hash
capability
status
expires_at nullable
created_by
created_at
revoked_at nullable
```

第一版匿名 capability：

```text
Read
```

---

# Part R: Asset

## 40. core.asset_blobs

物理 Blob：

```text
blob_id
object_key
sha256
size_bytes
mime_type
storage_class
created_at
```

---

## 41. core.assets

逻辑 Asset：

```text
asset_id
workspace_id
blob_id nullable
status
original_name
created_by
created_at
updated_at
```

---

## 42. Asset Status

```text
Created
Uploading
Verifying
Processing
Ready
Failed
Blocked
Deleted
```

---

## 43. Asset Reference Index

`core.asset_refs`：

```text
asset_id
resource_id
node_id nullable
ref_kind
updated_at
```

它是 Derived / Rebuildable Index，不是正文 Source of Truth。

---

# Part S: Realtime Ownership

## 44. collab.resource_ownership

用于：

```text
Resource Owner
Lease
Ownership Epoch
Fencing
```

逻辑字段：

```text
resource_id PK
owner_instance_id
epoch bigint
lease_until
updated_at
```

---

## 45. Ownership Transfer

新 Owner：

```text
epoch = epoch + 1
```

所有权威 Journal Advance 必须验证当前 Epoch。

旧 Owner 即使恢复也无法继续提交。

---

# Part T: Durable Yjs Journal

## 46. collab.resource_update_journal

第一阶段正式使用 PostgreSQL 承载 Durable Update Journal。

逻辑字段：

```text
resource_id
journal_seq bigint
ownership_epoch bigint
update_bytes bytea
update_hash
accepted_at
durable_at
```

Primary Key：

```text
(resource_id, journal_seq)
```

---

## 47. journal_seq

```text
per-resource monotonic
```

不是全局顺序。

可以作为 Durable Boundary 的持久化序号基础。

---

## 48. Journal Partition

第一阶段明确：

```text
HASH(resource_id)
```

Partition。

未来极大规模再通过 Migration 引入时间子分区，不预先复杂化。

---

# Part U: Checkpoint

## 49. collab.resource_checkpoints

Checkpoint Binary 存：

```text
S3 Object Storage
```

PostgreSQL 保存：

```text
checkpoint_id
resource_id
journal_seq
schema_version
object_key
sha256
size_bytes
status
created_at
verified_at nullable
```

---

## 50. Checkpoint Status

```text
Creating
Verified
Failed
Superseded
```

只有 `Verified` 可以成为恢复起点。

---

# Part V: History

## 51. collab.resource_versions

User-visible History Metadata：

```text
version_id
resource_id
kind
label nullable
journal_seq
created_by nullable
created_at
restore_of_version_id nullable
```

---

## 52. Version Kind

```text
Auto
Named
Restore
Import
AIApply
```

可扩展。

---

## 53. Version != Checkpoint

不能设计为：

```text
每个 Version 都必须一份 Checkpoint
```

History 是 Logical Boundary，Checkpoint 是恢复加速结构。

---

# Part W: Comment

## 54. collab.comment_threads

```text
thread_id
resource_id
anchor_type
node_id nullable
start_relative_position bytea nullable
end_relative_position bytea nullable
status
created_by
created_at
resolved_at nullable
resolved_by nullable
```

---

## 55. Anchor Type

```text
Resource
Node
TextRange
```

TextRange 使用编码的：

```text
Y.RelativePosition
```

绝不长期保存 absolute text offset。

---

## 56. Thread Status

```text
Open
Resolved
Detached
```

Detached 不自动 fuzzy rebind。

---

## 57. collab.comments

```text
comment_id
thread_id
author_id
body_json
created_at
edited_at nullable
deleted_at nullable
```

---

## 58. Tombstone

Comment Delete：

```text
row 保留
deleted_at 设置
ordinary query 不返回原 body
```

Thread 结构不破坏。

---

## 59. Lightweight Rich Text

`body_json` 只允许 Comment Schema：

```text
Bold
Italic
Code
Link
Mention
LineBreak
```

不能直接塞完整 Document Schema。

---

## 60. collab.comment_mentions

```text
comment_id
mentioned_account_id
created_at
```

Unique：

```text
(comment_id, mentioned_account_id)
```

Mention 不授予 Permission。

---

# Part X: Notification

## 61. collab.notifications

```text
notification_id
recipient_account_id
type
target_ref jsonb
payload jsonb
created_at
read_at nullable
source_event_id nullable
```

---

## 62. Notification Dedup

适用时使用 Unique：

```text
(recipient_account_id, source_event_id, type)
```

防止 Event 重复投递产生重复通知。

---

## 63. Permission Leak

Notification Payload 不保存无需长期存在的敏感全文。

点击 Target 时重新鉴权。

---

# Part Y: Async Task

## 64. work.tasks

语义由 `25` 拥有。

逻辑字段：

```text
task_id
task_type
state
stage nullable
priority
actor_account_id nullable
workspace_id nullable
resource_id nullable
input_ref nullable
result_ref nullable
retry_of_task_id nullable
retry_count
next_attempt_at nullable
cancel_requested_at nullable
created_at
queued_at nullable
started_at nullable
finished_at nullable
failure_code nullable
schema_version
current_attempt_id nullable
```

---

## 65. Task Index

至少：

```text
(state, priority, next_attempt_at)
(task_type, state)
(workspace_id, state)
(created_at)
```

---

# Part Z: Task Attempt

## 66. work.task_attempts

```text
attempt_id
task_id
attempt_number
worker_id
execution_epoch
state
claimed_at
lease_until
heartbeat_at
finished_at nullable
error_code nullable
```

Unique：

```text
(task_id, attempt_number)
```

Attempt 历史不可覆盖。

---

# Part AA: Task Effect

## 67. work.task_effects

用于 Retry 幂等副作用：

```text
effect_id
task_id
effect_key
effect_type
target_ref
status
provider_ref nullable
created_at
completed_at nullable
```

Unique：

```text
(effect_key)
```

---

# Part AB: AI ChangeSet

## 68. work.change_sets

```text
change_set_id
task_id nullable
workspace_id
created_by
state
current_revision
created_at
updated_at
```

---

## 69. work.change_set_revisions

```text
change_set_id
revision
base_context_ref
summary
created_at
```

Primary Key：

```text
(change_set_id, revision)
```

---

## 70. work.change_items

```text
change_item_id
change_set_id
revision
resource_id nullable
change_type
target_ref
payload jsonb
status
```

大型 Diff 进入 Object Storage，表中保存 Ref / Metadata。

---

# Part AC: Import / Export

## 71. work.import_sessions

```text
import_id
workspace_id
project_id nullable
stage
created_by
source_asset_id nullable
plan_ref nullable
result_ref nullable
task_id nullable
created_at
updated_at
expires_at nullable
```

---

## 72. work.export_sessions

```text
export_id
workspace_id
source_ref
format
stage
created_by
result_asset_id nullable
task_id
created_at
updated_at
expires_at
```

---

# Part AD: Search Coordination

## 73. work.search_index_state

只保存协调状态：

```text
resource_id
indexed_journal_seq
indexed_at
schema_version
last_error nullable
```

Search Data 本体在 OpenSearch。

该表可重建，不是正文真相。

---

# Part AE: Outbox

## 74. integration.outbox_events

```text
outbox_id
event_id
event_type
schema_version
aggregate_type
aggregate_id
payload jsonb
trace_id
created_at
published_at nullable
publish_attempts
```

`event_id` Unique。

---

## 75. Atomic Outbox

必须：

```text
business rows
+
outbox row
```

同一个 PostgreSQL Transaction Commit。

---

# Part AF: Inbox

## 76. integration.inbox_events

Consumer Dedup：

```text
consumer
event_id
received_at
processed_at nullable
status
error_code nullable
```

Unique：

```text
(consumer, event_id)
```

---

# Part AG: Webhook

## 77. integration.webhook_receipts

```text
receipt_id
provider
provider_event_id
event_type
received_at
signature_valid
status
payload_ref nullable
sanitized_payload jsonb nullable
processed_at nullable
```

Unique：

```text
(provider, provider_event_id)
```

---

# Part AH: Provider Delivery

## 78. integration.provider_deliveries

```text
delivery_id
provider
delivery_type
task_id nullable
event_id nullable
status
attempt_count
provider_message_id nullable
last_error_code nullable
created_at
updated_at
```

---

# Part AI: Audit

## 79. audit.entries

Append-oriented：

```text
audit_id
occurred_at
actor_type
actor_id nullable
action
workspace_id nullable
project_id nullable
resource_id nullable
target_ref jsonb
request_id nullable
trace_id nullable
metadata jsonb
```

---

## 80. Audit Mutation

普通 Application Role：

```text
不得 UPDATE / DELETE 既有 Audit Row
```

必须修正时走专门 audited operation。

---

# Part AJ: Transaction Boundaries

## 81. Create Resource

同一事务：

```text
resource row
initial explicit access if needed
outbox ResourceCreated
```

正文 Y.Doc 初始化走正式 Resource Workflow，不再建第二份正文表。

---

## 82. Rename Resource

同一事务：

```text
resource metadata
outbox ResourceRenamed
```

---

## 83. Permission Change

同一事务：

```text
permission row
owner invariant
outbox PermissionChanged
audit
```

---

## 84. Owner Transfer

必须：

```text
lock relevant project access rows
validate current owner
promote new owner
adjust old owner
ensure owner >= 1
outbox
audit
commit
```

---

## 85. Comment Create

同一事务：

```text
thread/comment
mention rows
outbox CommentCreated
```

Notification 通过 Event Consumer 异步产生，不能反向阻塞 Comment Commit。

---

## 86. Task Create

同一事务：

```text
task
outbox TaskCreated / QueueTrigger
```

NATS JetStream publish 在 Commit 后完成。

---

## 87. Session Login

同一事务：

```text
lock account
create new session
replace oldest if active device session > 2
outbox SessionReplaced when needed
audit security event
commit
```

---

## 88. Share Revoke

同一事务：

```text
share status
outbox ShareRevoked
audit
```

Realtime / Cache 失效通过 Event 加速。

---

# Part AK: Transaction Isolation

## 89. Default

默认：

```text
READ COMMITTED
```

竞争操作使用：

```text
SELECT ... FOR UPDATE
unique constraint
optimistic row version
```

---

## 90. SERIALIZABLE

不把整个系统默认设为 SERIALIZABLE。

只有明确 Use Case 经过测试后可局部使用。

---

# Part AL: Metadata Optimistic Version

## 91. row_version

需要防普通 Metadata Lost Update 的表可以使用：

```text
row_version bigint
```

---

## 92. Yjs 例外

Resource 正文是 CRDT。

不能重新引入：

```text
baseVersion
```

作为字符编辑冲突系统。

---

# Part AM: Index Strategy

## 93. 必须重点索引

```text
all foreign keys
project/folder tree
resource project/folder
project/resource permission lookup
session account/status
task state/priority/time
notification recipient/read
comment resource/status
outbox unpublished
inbox consumer/event
journal resource/seq
checkpoint resource/seq
history resource/time
```

---

## 94. Index Review

最终索引依据：

```text
EXPLAIN
query pattern
load test
production metrics
```

不能因为字段“以后也许会查”就全部加索引。

---

# Part AN: Partition

## 95. 第一阶段强制 Partition

```text
collab.resource_update_journal
```

按：

```text
HASH(resource_id)
```

分区。

---

## 96. 观察后再分区

候选：

```text
integration.outbox_events
audit.entries
collab.notifications
work.task_attempts
```

根据真实规模再启用，不预先泛化。

---

# Part AO: Retention

## 97. 独立 Retention

以下不能共享一个 TTL：

```text
Task
Task Attempt
Notification
One-time Token
Webhook Receipt
Provider Delivery
Audit
Journal
Checkpoint
Export Result
Import Temp
```

---

## 98. Journal GC

Journal 删除必须经过：

```text
Verified Checkpoint
+
Compaction Boundary
```

禁止普通 TTL 直接删除 Durable Journal。

---

# Part AP: Foreign Key / Cascade

## 99. Core FK

核心实体关系必须使用 Foreign Key。

---

## 100. Historical Reference

Audit / Event /历史记录允许引用已经 Purged 的 stable ID，因此不要求所有历史引用都 FK Cascade。

---

## 101. Cascade Delete

默认禁止依靠大型：

```text
ON DELETE CASCADE
```

一次删除整个 Workspace / Project。

Purge 使用受控 Async Task。

---

# Part AQ: Purge

## 102. Purge 是 Task

```text
Purge
→ 25 Async Task Runtime
```

不是 HTTP Request Thread 里直接巨大 DELETE。

---

## 103. Purge Flow

逻辑：

```text
revoke access
mark Purging
stop / reject realtime subscription
clean derived state
remove comments/history by retention policy
release asset references
remove journal/checkpoint
remove resource metadata
final audit
```

精确顺序由 Lifecycle Owner + Task Runtime 编排。

---

# Part AR: Read Model

## 104. Derived Read Model

允许：

```text
materialized view
denormalized read table
Valkey cache
OpenSearch index
```

但必须可重建，不能成为第二业务真相。

---

# Part AS: Migration

## 105. PostgreSQL Migration

全部通过：

```text
Alembic
```

---

## 106. Expand / Contract

生产流程：

```text
Expand
Deploy compatible code
Backfill
Switch read/write
Contract
```

---

## 107. Backfill

大型 Backfill：

```text
Async Task
batch
checkpoint
retryable
observable
```

禁止一个超长 Transaction。

---

# Part AT: Data Access Ownership

## 108. Repository Port

Application Module 通过自己的 Repository Port 写 Owner 表。

---

## 109. Cross-domain Read

复杂高性能 Query 可以使用专门 Read Repository 跨表 Join。

但跨 Domain 写入仍由 Owner Application Use Case 负责。

---

# Part AU: DB Roles

## 110. Process Roles

至少分：

```text
api role
realtime role
worker role
migration role
read-only diagnostics role
```

---

## 111. Realtime Role

Realtime DB Role 只可写：

```text
collab.resource_ownership
collab.resource_update_journal
collab.resource_checkpoints metadata
```

以及必要的只读技术表。

不能成为全库万能账号。

---

## 112. Migration Role

只有 Migration Role 拥有正式 DDL 权限。

Application Role 不使用 superuser。

---

# Part AV: Hard Constraints

## 113. 架构硬约束

1. 第一阶段使用一个权威 PostgreSQL 业务数据库。
2. PostgreSQL 逻辑 Schema 固定为 `auth/core/collab/work/integration/audit`。
3. 跨模块业务实体使用 UUIDv7。
4. Core Relationship 使用 Foreign Key。
5. JSONB 不得代替 Membership / Permission / Relationship。
6. 大型 Binary 不进入 PostgreSQL。
7. 最多两个 Active Device Sessions 必须在事务中可靠保证。
8. Provider Identity 必须 `UNIQUE(provider, provider_subject)`。
9. Project 必须保持至少一个 Owner。
10. Resource Type 不允许普通原地变更。
11. Durable Yjs Journal 第一阶段存 PostgreSQL。
12. Journal 使用 per-resource `journal_seq`，不定义全局业务顺序。
13. Journal 第一阶段按 `resource_id` Hash Partition。
14. Checkpoint Binary 存 S3，PostgreSQL 只存 Metadata。
15. 只有 Verified Checkpoint 可作为恢复起点。
16. History Version 不等于 Checkpoint。
17. Comment TextRange Anchor 使用编码 Y.RelativePosition。
18. Deleted Comment 保留 Tombstone。
19. Task / Attempt / Lease / Fencing 遵守 25。
20. Outbox 必须和业务状态同一 PostgreSQL Transaction。
21. Inbox 使用 `(consumer, eventId)` 去重。
22. Audit append-oriented。
23. 大规模 Purge 必须 Async Task，不依赖大规模 Cascade Delete。
24. PostgreSQL Migration 只通过 Alembic。
25. Resource / Yjs Schema Migration 不通过 Alembic 冒充数据库 Migration。
26. 默认 Isolation 为 READ COMMITTED，竞争操作显式 Lock / Constraint。
27. Yjs 正文不能重新引入传统 baseVersion 冲突模型。
28. Application DB Role 不得使用 superuser。
29. 每张表必须有唯一 Domain Owner。
