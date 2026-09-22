# Testing, Quality & Release Design

## 1. 目标

本设计定义系统的测试分层、质量门槛、Contract Test、数据库测试、Realtime / Offline / Multi-tab 测试、AI / Import / Asset 安全测试、性能测试、Migration Test、Release Gate、Canary、Rollback 和回归策略。

本模块解决：

> 一个同时包含 PostgreSQL、Yjs、Realtime、Offline、AI、Asset、Webhook、Permission、History 和多实例部署的系统，如何证明修改没有破坏既有架构约束，以及什么条件下一个版本才允许进入生产。

---

## 2. 核心原则

测试不是：

```text
为了让 CI 变绿
```

而是验证：

```text
Architecture Invariants
Business Rules
Failure Recovery
Security Boundaries
Compatibility
Performance
```

---

## 3. 测试金字塔

建议：

```text
Static Check
↓
Unit Test
↓
Contract Test
↓
Integration Test
↓
End-to-End Test
↓
Load / Failure / Security Test
```

不同层解决不同问题。

---

# Part A: Static Quality

## 4. 必须自动检查

至少：

```text
format
lint
typecheck
schema validation
migration validation
dependency scan
secret scan
```

---

## 5. TypeScript

前端：

```text
strict type checking
```

Client Contract 不允许大量：

```text
any
```

绕过。

---

## 6. Python

后端：

```text
type checking where practical
lint
test
```

核心 Contract / Domain Model 必须有明确类型。

---

## 7. Rust

如果使用 Rust：

```text
cargo check
clippy
test
```

进入 CI。

---

# Part B: Unit Test

## 8. Unit Test 范围

适合：

```text
pure domain rule
permission capability mapping
state machine
error mapping
adapter normalization
anchor helper
idempotency logic
```

---

## 9. 不要过度 Mock

Unit Test 可以 Mock 外部依赖。

但：

```text
PostgreSQL transaction
Yjs integration
WebSocket
```

不能全部只靠 Mock 证明正确。

---

# Part C: Contract Test

## 10. Contract Test 是核心 Gate

前后端必须验证：

```text
Command schema
Query schema
Event schema
Stream schema
Error schema
enum
version
required / optional field
```

---

## 11. Client Contract Compatibility

旧前端版本与新后端：

```text
必须在声明兼容窗口内工作
```

---

## 12. Event Compatibility

新 Consumer 需要兼容：

```text
旧 Event version
```

或明确 Migration / rollout plan。

---

## 13. Provider Contract

微信 / 飞书 / Email / Object Storage / AI Adapter：

```text
使用 fixture / sandbox / mock server
```

验证：

```text
success
timeout
rate limit
malformed response
version change
```

---

# Part D: PostgreSQL Integration Test

## 14. 真实 PostgreSQL

数据库核心测试：

```text
必须使用真实 PostgreSQL
```

不能只用：

```text
SQLite
```

替代生产语义。

---

## 15. 测试范围

至少：

```text
transaction
unique constraint
foreign key
concurrency
locking
outbox
migration
rollback
partition-related behavior if used
```

---

## 16. Identity Race

测试：

```text
same email concurrent register
same provider identity concurrent bind
single active session concurrent login
```

最终必须满足数据库约束。

---

## 17. Permission Race

测试：

```text
edit while permission downgrade
owner transfer race
member remove while active request
```

---

# Part E: Realtime / Yjs Test

## 18. Realtime 必须独立测试

至少：

```text
multi-client edit
concurrent insert
delete
move
disconnect
reconnect
state vector diff
worker restart
large update
slow client
```

---

## 19. Node Identity Test

至少覆盖：

```text
edit preserves nodeId
move preserves nodeId
duplicate creates new nodeId
split semantics
merge semantics
undo restores nodeId
remote sync preserves nodeId
```

---

## 20. Comment Anchor Test

至少：

```text
insert before text
delete before text
delete target node
undo target node
history restore
detached anchor
```

验证：

```text
NodeRef + RelativePosition
```

行为。

---

# Part F: Offline Test

## 21. Offline 场景

至少：

```text
open cached resource offline
edit offline
refresh offline
browser crash
reconnect
permission downgrade offline
session replaced offline
resource trashed offline
```

---

## 22. Offline Recovery

验证：

```text
Unsynced Local Content
```

不会因：

```text
logout
session replacement
permission loss
```

被静默删除。

---

# Part G: Multi-tab Test

## 23. 多 Tab

至少：

```text
same session multiple tabs
same resource multiple tabs
different resources
logout one tab
session replaced
notification update
cache invalidation
```

---

## 24. 多 Tab 不依赖 BroadcastChannel 正确性

关闭 / 丢失 BroadcastChannel 后：

```text
最终仍可通过 server validation / reconnect 恢复
```

---

# Part H: Permission / Security Test

## 25. Negative Authorization Test

每个受保护能力必须同时测试：

```text
allowed actor succeeds
forbidden actor fails
```

---

## 26. IDOR Test

随机替换：

```text
workspaceId
projectId
resourceId
assetId
threadId
taskId
```

必须无法越权。

---

## 27. Share Test

至少：

```text
valid share
expired
revoked
random token
read-only write attempt
```

---

## 28. Auth Test

至少：

```text
password login
wrong password
rate limit
session replacement
password reset
provider callback replay
state mismatch
```

---

## 29. Browser Security

至少：

```text
XSS payload
CSRF
CORS
open redirect
clickjacking header
```

---

## 30. SSRF Test

未来任何 URL Fetch 能力：

```text
localhost
private IP
metadata endpoint
redirect chain
DNS rebinding pattern
```

必须阻断。

---

# Part I: Asset / Import Test

## 31. File Security

至少：

```text
fake MIME
malformed image
malware fixture
oversized upload
dangerous SVG
```

---

## 32. Archive Security

至少：

```text
zip traversal
zip bomb
deep nesting
too many files
symlink
hardlink
absolute path
```

---

## 33. Import Partial Failure

验证：

```text
部分文件成功
部分失败
retry failed items
不会重复创建成功项
```

---

# Part J: AI Test

## 34. AI 不是只测 Prompt

必须测试：

```text
tool scope
permission
changeset
conflict
partial apply
retry
cancel
provider failure
prompt injection
```

---

## 35. Prompt Injection Test

Resource 中构造：

```text
要求模型越权读取其他 Workspace
要求调用未授权 Tool
要求绕过 ChangeSet
```

结果必须：

```text
Tool Layer 拒绝
```

---

## 36. AI Apply Race

用户生成 ChangeSet 后：

```text
Resource 被其他人修改
```

Apply 必须：

```text
rebase safely or conflict
```

不能旧状态整文覆盖。

---

# Part K: Event / Queue Test

## 37. At-least-once

重复投递：

```text
Comment Event
Notification Event
Asset Event
```

Consumer 必须幂等。

---

## 38. Event Loss Recovery

模拟 Consumer 长时间停止。

恢复后：

```text
backlog
replay
reconciliation
```

必须最终收敛。

---

## 39. Dead Letter

验证：

```text
进入 DLQ
可诊断
可 retry
retry 不重复副作用
```

---

# Part L: Webhook / Email Test

## 40. Webhook

至少：

```text
valid signature
invalid signature
replay
duplicate
unknown event
oversized payload
worker crash
```

---

## 41. Email

至少：

```text
queue
retry
hard bounce
provider outage
duplicate send request
template error
```

---

# Part M: Migration Test

## 42. Migration 必须单独测试

PostgreSQL Migration：

```text
不能只在本地跑成功
```

---

## 43. Expand / Contract

CI / Staging 至少验证：

```text
Old Code + Expanded Schema
New Code + Expanded Schema
Backfill
New Code after switch
Contract
```

---

## 44. Rollback

每次 Migration 必须回答：

```text
代码回滚后还能否读取当前 Schema
```

---

## 45. Data Migration

大数据 Backfill：

```text
必须可重启
可观察
可限速
```

不能单个超长事务。

### 45.1 Resource / Yjs Schema Migration Test

数据库 Schema Migration 之外，还必须测试持久化 Resource 内容本身的 Schema 演进。

至少保留真实旧版本 Fixture：

```text
Old Checkpoint
Old Durable Journal
Old Y.Doc / Resource Schema
Old nodeId layout
```

并验证：

```text
旧持久化状态可被新版本恢复
schemaVersion Migration 可重复 / 可恢复
已有 nodeId 不被无理由重建
NodeRef 仍能定位同一逻辑节点
Y.RelativePosition / Comment Anchor 不被静默错绑
History Preview / Restore 仍可读取旧版本
旧 Client 在不兼容 Schema 下被明确拒绝编辑或只读降级
Migration 失败不会污染最后一个 Verified Checkpoint / Durable Recovery Chain
```

不能只证明 PostgreSQL 表结构能升级，就认为 Resource Schema Migration 已经安全。

---

# Part N: End-to-End Test

## 46. E2E 重点

E2E 不追求覆盖每个按钮。

重点覆盖核心用户路径：

```text
register / login
create workspace
create resource
realtime edit
comment / mention
notification
history
AI changeset
asset upload
import / export
permission change
offline reconnect
```

---

## 47. E2E 必须跨真实边界

至少部分 E2E 使用：

```text
real PostgreSQL
real WebSocket
real Yjs integration
real browser
```

---

# Part O: Performance Test

## 48. API

验证：

```text
latency
throughput
error rate
connection pool
```

---

## 49. Realtime

至少：

```text
large connection count
many subscriptions
hot resource
many resources
reconnect storm
slow consumer
```

---

## 50. PostgreSQL

至少：

```text
permission query
journal write
outbox
task update
resource tree
history
connection pool
replica failover impact
```

---

## 51. Queue

至少：

```text
backlog growth
worker scale
oldest message age
retry storm
```

---

## 52. Asset

至少：

```text
parallel upload
large upload
processing backlog
```

---

# Part P: Load Acceptance

## 53. 性能基线

第一版不在架构文档硬编码具体 QPS。

但上线前必须记录：

```text
expected load
tested load
headroom
bottleneck
```

---

## 54. N+1

关键服务性能测试应验证：

```text
失去一个实例后
```

剩余容量仍可运行核心业务。

---

# Part Q: Failure Injection

## 55. 必测故障

至少：

```text
kill API
kill realtime worker
kill task worker
PostgreSQL failover
queue delay
search down
object storage slow
email provider down
AI provider down
network partition
```

---

## 56. Failure Acceptance

验证的不只是：

```text
服务最终恢复
```

还包括：

```text
用户状态是否正确
数据是否丢失
是否错误显示成功
是否可诊断
```

---

# Part R: Release Gate

## 57. Release 之前必须通过

至少：

```text
Static Check
Unit Test
Contract Test
Core Integration Test
Migration Check
Security Critical Test
Build Artifact
```

---

## 58. 高风险模块额外 Gate

以下变化需要更严格：

```text
Auth
Permission
Session
Realtime
Persistence
Migration
AI Apply
Import Parser
Share
Purge
```

至少增加：

```text
targeted integration
negative test
staging verification
```

---

# Part S: Staging

## 59. Staging 用途

```text
migration rehearsal
contract verification
provider sandbox
realtime smoke
offline smoke
release candidate
```

---

## 60. Staging 不等于 Production Data

禁止把真实生产用户数据随意复制到 Staging。

如需：

```text
sanitized / synthetic data
```

---

# Part T: Canary

## 61. Canary

高风险服务：

```text
Realtime
Permission
Persistence
Gateway
AI Apply
```

优先小流量发布。

---

## 62. Canary 观察

至少看：

```text
error rate
latency
reconnect
durable lag
permission denial anomaly
task failure
database load
```

---

## 63. Canary Stop

异常超过阈值：

```text
停止扩大
```

必要时：

```text
Rollback
```

---

# Part U: Rollback

## 64. 每次 Release 必须可回答

```text
如何 rollback code
如何处理 migration
如何处理 feature flag
如何处理 background task
```

---

## 65. 数据不可逆变化

如果 Migration 已产生不可逆数据变化：

```text
不能盲目代码回滚
```

必须走：

```text
forward fix
or
validated restore plan
```

---

# Part V: Feature Flag

## 66. 新功能

可以：

```text
disabled by default
internal
canary
workspace subset
percentage
general
```

逐步放量。

---

## 67. Kill Switch

高风险能力：

```text
AI Apply
Import
Provider Login
Webhook Delivery
```

应有紧急关闭能力。

---

# Part W: Regression Strategy

## 68. Bug 修复

每个重要 Bug：

```text
先复现
↓
添加 Regression Test
↓
修复
```

避免同类问题再次出现。

---

## 69. 架构回归

以下硬约束必须长期测试：

```text
Resource unique collaboration boundary
nodeId stability
no second mutable block tree
permission cannot be bypassed
AI writes through ChangeSet
search not source of truth
asset binary not in Y.Doc
single active session
```

---


## 69.1 Product Policy Regression

已确认产品规则必须进入回归测试，至少包括：

```text
Active Device Session Count ≤ 2
Archived Project read-only
Default Search excludes Archived
History = Edit / Manage / Owner
Trash / Restore = Manage / Owner
Purge = Owner
PendingVerification cannot create Workspace
Account Delete Grace = 30 days
Anonymous Share no comments / no presence
Flat Comment Thread
Resolve / Reopen capability
Resolved Thread requires Reopen before Reply
```

产品决策一旦进入 Architecture Constitution，就不能只依赖人工记忆。

---

# Part X: Test Data

## 70. Fixture

测试数据应：

```text
deterministic
minimal
readable
```

---

## 71. 随机测试

并发 / CRDT 场景可以使用：

```text
property-based
randomized sequences
```

但失败时必须：

```text
可复现 seed
```

---

# Part Y: Flaky Test

## 72. Flaky 不可忽略

Flaky Test：

```text
必须修
```

不能长期：

```text
retry 3 times until green
```

掩盖 Race。

---

## 73. Realtime Flaky

特别关注：

```text
timing-dependent
network wait
arbitrary sleep
```

优先使用：

```text
condition-based await
deterministic hooks
```

---

# Part Z: CI

## 74. CI 分层

可以：

```text
PR Fast Gate
Merge Gate
Nightly
Pre-release
```

---

## 75. PR Fast Gate

至少：

```text
lint
typecheck
unit
contract
selected integration
```

---

## 76. Nightly

适合：

```text
long realtime
offline
load smoke
security scan
provider sandbox
```

---

## 77. Pre-release

必须：

```text
full migration rehearsal
critical E2E
canary plan
rollback plan
release notes
```

---

# Part AA: Quality Signals

## 78. 不看单一 Coverage

Coverage 是参考。

不能：

```text
90% coverage
= 系统一定正确
```

更重要：

```text
critical path
negative path
failure path
race
```

---

## 79. 必须追踪

建议：

```text
test failure rate
flaky rate
escaped defect
rollback frequency
migration failure
realtime incident
permission incident
```

---

# Part AB: Release Artifact

## 80. Artifact

生产 Artifact：

```text
versioned
immutable
traceable
```

至少关联：

```text
git commit
build
dependency lock
migration version
```

---

## 81. Client Version

Web 客户端也必须：

```text
可识别版本
```

方便旧 Tab 问题定位。

---

# Part AC: Acceptance Matrix

## 82. 核心上线验收

上线前至少验证：

```text
Auth
Permission
Workspace / Resource
Realtime
Persistence
Offline
Comment / Notification
History
Search
AI
Asset
Import / Export
Gateway / Provider
Backup / Restore
Observability
Security
```

---

# Part AD: 典型验收场景

## 83. 场景 1：两用户并发编辑

A、B 同时编辑同 Resource。

结果：

```text
Yjs convergence
nodeId stable
no overwrite
```

---

## 84. 场景 2：Realtime Worker Crash

编辑过程中 Worker 崩溃。

结果：

```text
reconnect
checkpoint + journal restore
state vector sync
no permanent loss
```

---

## 85. 场景 3：离线编辑后权限下降

结果：

```text
local content preserved
server write rejected
read-only
recovery available
```

---

## 86. 场景 4：单设备 Session Race

两个设备同时登录。

结果：

```text
最终只有一个 Active Session
```

---

## 87. 场景 5：AI ChangeSet Conflict

生成后 Resource 被修改。

结果：

```text
safe rebase or conflict
no stale overwrite
```

---

## 88. 场景 6：Webhook 重复

结果：

```text
one business effect
```

---

## 89. 场景 7：PostgreSQL Failover

结果：

```text
app reconnect
core service resumes
no manual full restart
```

---

## 90. 场景 8：Search 全丢

结果：

```text
editing unaffected
full reindex restores search
```

---

## 91. 场景 9：Migration Rollout

Old / New service coexist。

结果：

```text
no schema break
```

---

## 92. 场景 10：Bad Release

Canary error spike。

结果：

```text
stop rollout
rollback
diagnostic by version
```

---

# Part AE: Hard Constraints

## 93. 架构硬约束

1. PostgreSQL 核心测试必须使用真实 PostgreSQL，不得用 SQLite 替代生产语义。
2. Contract Test 是前后端兼容性 Release Gate。
3. Realtime / Yjs 必须有真实多客户端测试。
4. Offline / Multi-tab 必须独立测试。
5. Permission 必须有 Negative Authorization Test。
6. IDOR 必须自动测试。
7. AI 必须测试 Tool Scope / ChangeSet / Prompt Injection，而不只是 Prompt 文本。
8. Import / Asset 必须测试恶意文件和 Archive。
9. Event / Queue Consumer 必须测试重复投递和幂等。
10. Migration 必须测试 Expand / Contract 和 Rollback Compatibility。
11. Load Test 不能只测 HTTP QPS。
12. Failure Injection 必须验证用户状态和数据正确性。
13. 高风险模块发布必须有额外 Gate。
14. Release 必须有 Canary / Rollback Plan。
15. Flaky Test 必须治理，不能长期靠 Retry 掩盖。
16. Bug Fix 应增加 Regression Test。
17. 架构硬约束必须变成长期自动化测试。
18. 生产 Artifact 必须版本化、不可变、可追踪。
19. Staging 不得随意使用真实生产数据。
20. 测试、发布和日志诊断必须能通过版本关联。
21. Resource / Yjs Schema Migration 必须使用旧持久化 Fixture 做兼容性测试，并验证 nodeId、NodeRef、RelativePosition 与恢复链不被破坏。
21. Generic Async Task / Attempt / Lease / Retry / Fencing 测试必须遵守 `25-Async-Task-Execution-Design.md`。
22. 本设计与 15、21、22、23、25 号设计保持一致。

---

## 94. 最终模型

```text
Code Change
↓
Static Check
↓
Unit
↓
Contract
↓
Integration
↓
E2E
↓
Security / Failure / Load
↓
Staging
↓
Canary
↓
Production
↓
Observe
↓
Rollback / Expand
```

系统必须保证：

> 一个版本进入生产，不是因为“代码能跑”，而是因为它已经证明不会破坏协议、权限、PostgreSQL 一致性、Realtime 收敛、Offline 恢复、AI 安全边界和既有架构硬约束，并且出问题时能够快速定位和回滚。
