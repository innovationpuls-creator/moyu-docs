# Async Task Execution Design

## 1. 目标

本设计定义系统中所有长时间、可恢复、可重试后台工作的统一 Async Task Runtime。

本模块解决：

> AI、Import、Export、Asset Processing、Search Reindex、History Restore、Purge、Migration、Checkpoint 等任务如何使用同一套 Task / Attempt / Lease / Retry / Cancel / Progress / Priority / Dead Letter / Recovery 机制，而不是每个业务模块分别实现一套后台任务系统。

本设计是通用 Task Runtime 的 Canonical Owner。

Domain 模块只能增加：

```text
taskType
domain stage
domain payload
domain result
```

不得重新定义：

```text
taskId
attempt
lease
retry
cancel
generic task state
worker recovery
queue reliability
```

---

## 2. 核心原则

统一模型：

```text
Domain Command
↓
Persistent Task
↓
Queue Trigger
↓
Worker Claim
↓
Task Attempt
↓
Domain Handler
↓
Authoritative State Change
↓
Task Result
```

关键规则：

```text
PostgreSQL Task State
= Source of Truth

Queue Message
= Execution Trigger

Worker Memory
= Temporary Runtime

Task Stream
= Realtime Feedback
```

Queue、WebSocket、Worker Memory 都不是 Task 的权威状态。

---

## 3. 适用范围

统一 Async Task Runtime 至少服务：

```text
AI Task
Import
Export
Asset Processing
Search Reindex
History Restore
Resource Purge
Project Purge
Schema / Data Migration
Large Checkpoint
Compaction
Reconciliation
Provider Delivery
Operational Repair
```

---

## 4. 不适用范围

以下不应强行进入 Async Task：

```text
普通 Query
普通低延迟 Command
每次键盘输入
Yjs Update
Awareness
普通 Comment Create
普通 Resource Rename
```

这些继续走各自正式路径。

---

# Part A: Task Identity

## 5. taskId

每个逻辑后台任务拥有稳定：

```text
taskId
```

一个 Task 从创建到最终完成：

```text
taskId 不变
```

---

## 6. attemptId

每次 Worker 实际执行 Task：

```text
创建 attemptId
```

因此：

```text
Task
├── Attempt 1
├── Attempt 2
└── Attempt 3
```

自动 Retry：

```text
taskId 相同
attemptId 不同
```

---

## 7. requestId

创建 Task 的 Client Command 有：

```text
requestId
```

它只代表：

```text
那一次具体请求
```

不代表 Task 生命周期。

---

## 8. idempotencyKey

创建 Task 的 Mutating Command 需要：

```text
idempotencyKey
```

重复提交同一逻辑请求：

```text
不得创建多个等价 Task
```

---

## 9. operationId

跨 Resource / 多阶段业务可以拥有：

```text
operationId
```

例如：

```text
AI Multi-resource Apply
Project Import
Bulk Purge
```

一个 Operation 可以关联一个或多个 Task。

---

# Part B: Task State

## 10. Canonical Task State

通用 Task State 固定为：

```text
Created
Queued
Running
WaitingForUser
Retrying
Succeeded
PartialSucceeded
Failed
Cancelled
```

这些状态由本设计统一解释。

---

## 11. Created

```text
Created
```

表示：

> Task 已经可靠创建，但尚未进入可执行队列。

它通常是很短的过渡状态。

---

## 12. Queued

```text
Queued
```

表示：

> Task 已经可以被 Worker 领取执行。

不表示已经有 Worker 正在工作。

---

## 13. Running

```text
Running
```

表示：

> 当前存在一个有效 Execution Attempt 正在执行。

---

## 14. WaitingForUser

```text
WaitingForUser
```

表示：

> Task 已经到达一个必须等待用户输入、确认或解决冲突的阶段。

例如：

```text
Import conflict decision
AI user clarification
Explicit recovery choice
```

WaitingForUser：

```text
不占用长期 Worker Lease
```

---

## 15. Retrying

```text
Retrying
```

表示：

> 上一个 Attempt 因可恢复故障失败，系统已经决定自动重试，但下一 Attempt 尚未开始。

至少记录：

```text
nextAttemptAt
retryCount
lastFailure
```

---

## 16. Succeeded

```text
Succeeded
```

表示：

> Task 的预期业务目标已经完成，并且最终结果已经进入其对应的正式 Domain Source of Truth。

---

## 17. PartialSucceeded

```text
PartialSucceeded
```

只用于：

> 一个正式允许部分完成的业务任务，部分子目标已经产生合法、不可伪装成失败的结果，但整体未全部完成。

例如：

```text
Project Import
Bulk Operation
Multi-resource Operation
```

必须提供：

```text
succeeded items
failed items
recovery / retry path
```

---

## 18. Failed

```text
Failed
```

表示：

> Task 已经停止自动执行，当前逻辑任务未成功完成。

Failed 必须区分：

```text
retryable exhausted
permanent failure
policy rejection
dependency failure
invalid state
```

---

## 19. Cancelled

```text
Cancelled
```

表示：

> Task 已经响应取消请求，并保证不会继续产生新的业务副作用。

不能仅因为：

```text
用户点了 Cancel
```

就立即伪造：

```text
Cancelled
```

---

## 20. Terminal State

终态：

```text
Succeeded
PartialSucceeded
Failed
Cancelled
```

自动 Retry 不改变：

```text
taskId
```

但终态后的人工 Retry：

```text
创建新的 Task
```

并记录：

```text
retryOfTaskId
```

这样旧任务的最终历史保持不可歧义。

---

# Part C: Domain Stage

## 21. Generic State 与 Domain Stage 分离

通用 Task State 不承载业务细节。

例如 AI：

```text
Task State = Running
AI Stage   = GeneratingChangeSet
```

Import：

```text
Task State = Running
Import Stage = Validating
```

Export：

```text
Task State = Running
Export Stage = Packaging
```

---

## 22. Domain 不新增平行 Task State

以下属于 Domain Stage：

```text
ReadyForReview
Applying
Uploading
Inspecting
Validating
Preparing
Packaging
Ready
```

它们不能再成为另一套 Generic Task State。

---

# Part D: Task Persistence

## 23. PostgreSQL 是 Task Source of Truth

Task 权威状态存入：

```text
PostgreSQL
```

至少表达：

```text
taskId
taskType
state
stage
actor
scope
priority
createdAt
updatedAt
queuedAt
startedAt
finishedAt
retryCount
nextAttemptAt
cancelRequestedAt
resultRef
failureCode
schemaVersion
```

具体表结构由 PostgreSQL Logical Data Model 设计决定。

---

## 24. Queue 不是 Task 数据库

Queue Message 可以丢失、重复、延迟。

系统正确性不能依赖：

```text
“Queue 里还有这个消息”
```

判断 Task 是否存在。

---

## 25. Transactional Creation

典型创建流程：

```text
Domain Command
↓
PostgreSQL Transaction
├── Create Task
└── Outbox Event
↓
Commit
↓
Dispatcher
↓
Queue
```

避免：

```text
Task 创建成功
但 Queue 消息永久丢失
```

---

# Part E: Queue Semantics

## 26. Delivery Semantics

Worker Queue 使用：

```text
At-least-once
```

语义。

不承诺：

```text
Exactly Once
```

---

## 27. Duplicate Delivery

同一 Task Queue Message：

```text
可能重复
```

Worker 必须先：

```text
Claim Task
```

成功后才能执行。

重复 Consumer：

```text
不得产生双重业务效果
```

---

## 28. Queue Message

Queue Message 尽量只包含：

```text
taskId
taskType
routing metadata
schemaVersion
```

大型 Payload：

```text
存 PostgreSQL / Object Storage
```

通过引用获取。

---

# Part F: Worker Claim / Lease / Fencing

## 29. Worker Claim

Worker 开始执行前必须原子 Claim：

```text
Queued / Retrying
↓
Running
```

并创建：

```text
attemptId
lease
executionEpoch
```

或等价安全机制。

---

## 30. Lease

有效 Attempt 拥有：

```text
leaseUntil
```

Worker 运行期间：

```text
heartbeat
```

续租。

---

## 31. Worker Crash

Worker Crash：

```text
heartbeat stops
↓
lease expires
↓
Task becomes recoverable
↓
new Attempt
```

不会永久卡在：

```text
Running
```

---

## 32. Attempt Fencing

仅有 Lease Timeout 不够。

必须保证：

> 新 Attempt 生效后，旧 Attempt 即使因为网络恢复、GC Pause 结束或线程重新运行，也不能继续作为有效执行者提交受保护的 Task 状态。

使用：

```text
executionEpoch
fencing token
attempt ownership version
```

或等价机制。

---

## 33. Domain Side Effect Fencing

对于数据库状态变化：

```text
提交时验证 current attempt authority
```

对于 Resource Change：

```text
仍必须通过 Resource / Permission / ChangeSet 等正式 Domain 边界
```

不能因为 Worker 持有 Lease 就绕过 Domain。

---

# Part G: Retry

## 34. 自动 Retry

仅对：

```text
明确可恢复故障
```

自动 Retry。

例如：

```text
network timeout
temporary provider 5xx
temporary queue / dependency unavailable
transient database conflict
```

---

## 35. 不自动 Retry

例如：

```text
Validation
Permission
Authentication
Unsupported Format
Permanent Provider Rejection
Invalid Resource State
```

直接进入：

```text
Failed
```

或对应业务等待状态。

---

## 36. Retry Policy

统一至少包含：

```text
maxAttempts
backoff
jitter
retryable error classifier
nextAttemptAt
```

具体数值按 taskType 配置。

---

## 37. Retry-After

外部 Provider 返回：

```text
Retry-After
```

时，在安全范围内应尊重该提示。

---

## 38. Retry Budget

不能无限 Retry。

限制：

```text
attempt count
elapsed time
queue budget
provider budget
```

---

## 39. Manual Retry

终态 Failed 后，人工：

```text
RetryTask
```

创建：

```text
new taskId
retryOfTaskId = old taskId
```

新 Task 重新进行：

```text
Permission
Lifecycle
Current State
```

检查。

---

# Part H: Idempotent Effects

## 40. Task Retry 不等于重复业务效果

Worker 可能：

```text
执行成功
↓
Ack 前崩溃
↓
Queue 再次投递
```

因此外部效果必须可检测重复。

---

## 41. effectKey

重要副作用应具备稳定：

```text
effectKey
```

概念。

例如：

```text
taskId + stage + target + operation
```

---

## 42. Database Effect

优先依赖：

```text
unique constraint
transaction
idempotency record
```

保证重复执行安全。

---

## 43. Provider Effect

Provider 支持 Idempotency Key 时：

```text
使用稳定 Provider Idempotency Key
```

不支持时：

```text
系统自己记录 delivery / effect result
```

并采用安全恢复策略。

---

# Part I: Cancellation

## 44. Cancel Request

取消通过：

```text
CancelTask
```

产生：

```text
cancelRequestedAt
```

---

## 45. Cooperative Cancellation

Worker 在安全检查点：

```text
检查 cancel request
```

例如：

```text
before expensive stage
before next item
before external provider call
before irreversible commit
```

---

## 46. 不可中断区

正在执行：

```text
数据库 Commit
Resource Apply
Provider request
```

时不一定能瞬时取消。

系统必须：

```text
等待当前安全边界
```

然后确定最终状态。

---

## 47. Cancel 与 Side Effect

如果取消请求到达时：

```text
业务效果已经正式 Commit
```

Task 不能谎报：

```text
Cancelled
```

应根据业务结果进入：

```text
Succeeded
PartialSucceeded
```

或 Domain 定义的恢复状态。

---

# Part J: WaitingForUser

## 48. WaitingForUser 不持有 Worker

进入：

```text
WaitingForUser
```

时：

```text
释放 Worker
释放 Lease
持久化等待原因
```

---

## 49. Resume

用户提供输入：

```text
ResumeTask Command
↓
validate current state
↓
Queued
↓
new Attempt
```

---

## 50. 等待过期

需要时可以设置：

```text
expiresAt
```

超时后进入：

```text
Failed
Cancelled
```

由 taskType Policy 定义。

---

# Part K: Progress

## 51. Progress Model

Task Progress 至少可表达：

```text
stage
messageCode
current
total
percentage
updatedAt
```

字段按任务实际能力选用。

---

## 52. 不伪造百分比

如果系统无法知道：

```text
total
```

则不要制造虚假 percentage。

可以仅返回：

```text
stage
messageCode
```

---

## 53. Progress Coalescing

高频 Progress：

```text
合并
限频
```

避免：

```text
每处理一行就写 PostgreSQL + 发 Event
```

---

## 54. Progress Source of Truth

客户端实时看到：

```text
Task Stream
```

但最终状态由：

```text
GetTask
```

恢复。

---

# Part L: Result

## 55. ResultRef

Task 不把大型结果直接塞入 Task Row。

使用：

```text
resultRef
```

指向：

```text
ChangeSet
Asset
Export Result
Import Result
Operation
Search Reindex Report
```

---

## 56. Result 生命周期

Task Metadata Retention：

```text
不等于 Result Retention
```

例如：

```text
Export download
```

可以短期过期，但 Task 记录继续保留。

---

# Part M: Priority / Fairness

## 57. Canonical Priority

统一优先级：

```text
Interactive
Normal
Background
Maintenance
```

---

## 58. Interactive

例如：

```text
用户主动启动的短 AI Task
用户等待的 History Restore
```

---

## 59. Normal

例如：

```text
Import
Export
Asset Processing
```

---

## 60. Background

例如：

```text
Search Reindex
Reconciliation
Preview Generation
```

---

## 61. Maintenance

例如：

```text
Compaction
Migration
Cleanup
Repair
```

---

## 62. Priority 不代表无限抢占

高优先级：

```text
可以先调度
```

但不能让 Background 永久饥饿。

---

## 63. Tenant Fairness

调度至少考虑：

```text
user
workspace
taskType
priority
```

防止单个 Workspace 把 Worker Pool 占满。

---

## 64. Concurrency Limit

可配置：

```text
global concurrency
taskType concurrency
workspace concurrency
user concurrency
provider concurrency
```

---

# Part N: Worker Pools

## 65. 不同工作负载隔离

至少逻辑隔离：

```text
AI Worker
Import / Export Worker
Asset Worker
Search Worker
Maintenance Worker
```

---

## 66. Bulkhead

某个：

```text
AI Provider
```

卡死时：

```text
不能耗尽 Import Worker
```

---

## 67. Worker Language

Task Runtime 是协议，不要求所有 Worker 使用同一种语言。

可以：

```text
Python Worker
TypeScript Worker
Rust Worker
```

只要遵守统一 Task Contract。

---

# Part O: Task Type Registry

## 68. TaskType

所有 Task 注册：

```text
taskType
```

例如：

```text
ai.generate
import.project
export.project
asset.process
search.reindex
history.restore
resource.purge
maintenance.compact
```

---

## 69. Task Handler

每个 Task Type 定义：

```text
input schema
result schema
retry policy
cancel policy
priority default
permission policy
retention policy
handler version
```

---

## 70. 禁止散落 if taskType

Task Runtime 不应该到处：

```text
if type == ...
```

使用：

```text
TaskType Registry
```

统一注册。

---

# Part P: Security / Permission

## 71. Actor

Task 保存：

```text
initiating actor
```

用于：

```text
audit
scope
diagnostics
```

---

## 72. Permission Snapshot 不是长期授权

Task 创建时可以保存：

```text
permission snapshot metadata
```

用于解释。

但不能用它代替：

```text
当前 Permission
```

---

## 73. 执行前 Re-check

重要写入前：

```text
re-check Account
re-check Permission
re-check Resource Lifecycle
```

尤其：

```text
AI Apply
Import Apply
History Restore
Purge
Export sensitive data
```

---

## 74. Session Replacement

客户端 Session 被替换：

```text
不自动取消所有后台 Task
```

Task 与 Browser Connection 分离。

但后续敏感操作仍依据：

```text
Account / Permission / Task authorization
```

---

## 75. Account Disabled

Account Disabled 后：

```text
未完成的用户发起 Task
```

在下一安全检查点应停止产生新的高风险副作用。

具体结果：

```text
Failed / Cancelled
```

由 taskType 决定。

---

## 76. Task Payload

Task Payload 不保存：

```text
Password
Session Cookie
Provider Secret
长期 Access Token
```

只保存：

```text
稳定业务引用
```

---

# Part Q: Dead Letter

## 77. Dead Letter 定位

Dead Letter 是：

```text
执行 / Delivery 的运维处置状态
```

不是新的业务 Task State。

Task 最终仍然是：

```text
Failed
```

---

## 78. 进入 Dead Letter

例如：

```text
retry exhausted
unknown handler version
repeated protocol error
poison message
```

可以进入：

```text
Dead Letter Queue / Dead Letter Record
```

---

## 79. Dead Letter 必须可诊断

至少：

```text
taskId
attemptId
taskType
failureCode
attempt count
last error
first failure
last failure
```

---

## 80. Dead Letter 操作

支持：

```text
Inspect
Replay as new controlled attempt/task
Discard with Audit
```

不能直接修改数据库假装成功。

---

# Part R: Reconciliation

## 81. Queue 丢消息仍可恢复

由于 PostgreSQL 是 Source of Truth：

```text
Queued / Retrying
```

Task 长时间没有 Queue Delivery 时：

```text
Reconciler
```

应重新投递。

---

## 82. Zombie Running Task

```text
Running
+
expired lease
```

由 Reconciler：

```text
recover
```

---

## 83. Stuck WaitingForUser

可以监控：

```text
age
expiry
```

但不能自动猜用户决定。

---

# Part S: Graceful Deployment

## 84. Worker Drain

部署时 Worker：

```text
stop claiming new tasks
↓
finish current safe unit
↓
release / finish lease
↓
exit
```

---

## 85. Hard Shutdown

如果实例被强杀：

```text
Lease Expiry
↓
New Attempt
```

恢复。

---

## 86. Mixed Version

滚动发布时可能存在：

```text
Worker vN
Worker vN+1
```

Task Payload 必须有：

```text
schemaVersion
```

---

## 87. Handler Version

TaskType 可以记录：

```text
handlerVersion
```

用于：

```text
compatibility
diagnostics
migration
```

---

## 88. Unknown Version

Worker 不认识 Task Schema：

```text
不能盲目执行
```

应：

```text
reject claim / fail safely / route compatible worker
```

---

# Part T: Multi-region / DR

## 89. 第一阶段

遵守 Deployment Design：

```text
Single Region Multi-AZ
+
Cross Region DR
```

---

## 90. DR 恢复

恢复 PostgreSQL 后：

```text
Queued
Retrying
Running with expired lease
```

Task 通过：

```text
Reconciliation
```

恢复。

---

## 91. 外部 Side Effect 不确定性

灾难发生在：

```text
Provider 成功
但本地记录未完成
```

时不能盲目重试。

必须根据：

```text
effectKey
provider idempotency
delivery record
reconciliation
```

判断。

---

# Part U: Domain Integration

## 92. AI

`12-AI-Task-ChangeSet-Design.md` 负责：

```text
AI Stage
Tool
Context
ChangeSet
Apply
```

本设计负责：

```text
Task / Attempt / Retry / Lease / Cancel / Worker
```

---

## 93. Import / Export

`13-Import-Export-Design.md` 负责：

```text
Import / Export Session
Plan
Format Adapter
Result
```

本设计负责后台执行 Runtime。

---

## 94. Asset

Asset Processing：

```text
scan
preview
transcode
metadata extraction
```

可以使用统一 Task Runtime。

---

## 95. Search

Search Reindex：

```text
Task Runtime
+
Search Domain Stage
```

Index 本身仍由 Search Design 管理。

---

## 96. History

大型 Restore：

```text
Async Task
```

但正式 Resource Change 仍遵守：

```text
History / Resource / Realtime
```

边界。

---

## 97. Purge

Purge 属于高风险 Task。

必须：

```text
Owner Permission
Audit
Current Lifecycle Check
Idempotent Cleanup
```

---

# Part V: Client Contract

## 98. Generic Query

正式客户端可通过统一能力：

```text
GetTask
ListTasks
```

获得当前权威状态。

---

## 99. Generic Command

按 Task Type 支持：

```text
CancelTask
ResumeTask
RetryTask
```

不是所有 Task 都必须支持全部 Command。

---

## 100. Task Stream

客户端可以订阅：

```text
TaskProgress
TaskStateChanged
```

但断线后：

```text
GetTask
```

恢复。

---

## 101. Frontend State

前端不得自己推断：

```text
Worker 正在执行
```

权威状态来自：

```text
Task Query / Event / Stream
```

---

# Part W: Event Model

## 102. Generic Task Events

统一事件：

```text
TaskCreated
TaskQueued
TaskStarted
TaskWaitingForUser
TaskRetryScheduled
TaskSucceeded
TaskPartiallySucceeded
TaskFailed
TaskCancelled
```

---

## 103. Progress Event

Progress 可通过：

```text
TaskProgressUpdated
```

但应：

```text
coalesce
```

避免事件洪水。

---

## 104. Domain Event

Generic Task Event：

```text
不替代 Domain Event
```

例如 Export 完成仍可以产生：

```text
ExportCompleted
```

Domain 消费者不应被迫理解所有 Task 内部状态。

---

# Part X: Observability

## 105. Task Diagnostic

每个 Task 至少可查：

```text
taskId
taskType
state
stage
priority
createdAt
queueWait
runDuration
attemptCount
retryCount
current attempt
last errorCode
resultRef
related trace
```

---

## 106. Attempt Diagnostic

每个 Attempt：

```text
attemptId
workerId
executionEpoch
claimedAt
leaseUntil
heartbeatAt
finishedAt
result
errorCode
```

---

## 107. Metrics

至少：

```text
task created rate
queue wait
run duration
success rate
failure rate
retry rate
cancel latency
lease expiry
stuck task
dead letter
per taskType backlog
oldest queued age
```

---

## 108. Logs

Task Log 使用：

```text
taskId
attemptId
traceId
operationId
resourceId where applicable
```

关联。

不记录完整敏感 Payload。

---

# Part Y: Retention

## 109. Task Retention

Task Metadata：

```text
可配置 Retention
```

不同 taskType 可以不同。

---

## 110. Audit 与 Task 不同

高风险操作的 Audit：

```text
不能因为 Task Retention 到期一起删除
```

---

## 111. Result Cleanup

大型临时 Result：

```text
Export ZIP
Import temp
Preview
```

按各 Domain Retention 清理。

---

# Part Z: Testing

## 112. 基础测试

统一 Task Runtime 至少测试：

```text
create
queue
claim
run
success
failure
cancel
retry
manual retry
waiting/resume
```

---

## 113. At-least-once Test

模拟：

```text
Worker 完成 Side Effect
↓
Ack 前 Crash
↓
Duplicate Delivery
```

不能产生重复业务效果。

---

## 114. Lease Test

模拟：

```text
Worker A stop heartbeat
↓
Worker B reclaim
↓
Worker A returns late
```

A 的 stale execution：

```text
必须被 fencing
```

---

## 115. Queue Loss Test

Task 已在 PostgreSQL：

```text
Queue Message 丢失
```

Reconciler 必须重新投递。

---

## 116. Retry Storm Test

Provider 大面积失败时：

```text
backoff
jitter
retry budget
circuit breaker
```

共同限制重试风暴。

---

## 117. Cancel Race

测试：

```text
Cancel 与 Commit 同时发生
```

最终不能：

```text
业务已成功
但 Task 显示 Cancelled
```

---

## 118. Deployment Test

Worker 滚动重启期间：

```text
Task 不丢
Task 不双写
Lease 正确恢复
```

---

# Part AA: 第一版不做

## 119. 不实现通用 Workflow Engine

第一版 Async Task Runtime 不做：

```text
任意 DAG 编辑器
用户自定义 Workflow DSL
通用 BPMN
Cron 产品
复杂跨 Task Saga Engine
```

---

## 120. 不追求 Exactly Once

正确模型：

```text
At-least-once execution
+
Idempotent Effect
+
Fencing
+
Reconciliation
```

而不是声称：

```text
Exactly Once
```

---

## 121. 不把 Queue 当数据库

禁止：

```text
Task 状态只存在 Redis / NATS / RabbitMQ
```

权威 Task State 必须可持久恢复。

---

# Part AB: 实现自由度

## 122. 本地 AI 可以选择

技术实现已由后续 Canonical Owner 冻结：

```text
Queue / Event Bus → NATS JetStream（26）
Task / Attempt / Effect PostgreSQL Logical Model → 29
Worker physical layout → 27
```

以下仍属于实现参数，而不是架构产品选择：

```text
具体 Claim SQL
具体 Lease 时长
具体 Backoff 数值
Worker Process Count
per-task concurrency limit
```

但不得改变：

```text
Persistent Task Source of Truth
At-least-once
Attempt Identity
Lease
Fencing
Idempotent Effect
Retry Budget
Cancellation Semantics
Reconciliation
```

---

# Part AC: 架构硬约束

## 123. 架构硬约束

1. Async Task Runtime 是所有通用后台任务执行语义的唯一 Canonical Owner。
2. `taskId` 标识一个逻辑 Task；`attemptId` 标识一次实际执行。
3. PostgreSQL 中的 Task State 是权威 Source of Truth。
4. Queue Message 只负责触发执行，不是 Task Source of Truth。
5. Task Queue 使用 At-least-once 语义，不声称 Exactly Once。
6. Task 创建必须通过本地事务 + Outbox 或等价可靠方式进入执行链。
7. Worker 执行前必须 Claim Task。
8. Running Attempt 必须具有 Lease / Heartbeat。
9. 新 Attempt 接管以后，旧 Attempt 必须被 Fencing。
10. 所有可重复 Side Effect 必须具备幂等保护。
11. 自动 Retry 只用于明确可恢复错误，并受 Retry Budget 限制。
12. 自动 Retry 保持同一 taskId，创建新的 attemptId。
13. 终态后的人工 Retry 创建新的 taskId，并通过 retryOfTaskId 关联原 Task。
14. Cancel 是请求，不等于瞬时 Cancelled。
15. 只有确认不会继续产生新副作用时才能进入 Cancelled。
16. WaitingForUser 不长期占用 Worker Lease。
17. Generic Task State 与 Domain Stage 必须分离。
18. Domain 模块不得重新发明 Task / Attempt / Lease / Retry 基础设施。
19. Task Progress 可以实时 Stream，但最终状态必须可 Query 恢复。
20. Session 断开、Tab 关闭不会自动终止后台 Task。
21. 高风险 Side Effect 执行前必须重新检查 Account / Permission / Lifecycle。
22. Task Payload 不得保存 Password / Session Credential / Provider Secret。
23. 大型 Task Result 使用 ResultRef，不塞入普通 Task Row。
24. Worker Pool 必须支持 Bulkhead 和并发限制。
25. 单 Workspace / User 不得无限占用全部 Worker Capacity。
26. Retry / Queue / Lease 故障必须可通过 Reconciliation 恢复。
27. Dead Letter 是失败处置机制，不是平行的业务 Task State。
28. Rolling Deployment 必须支持旧 / 新 Worker 共存和 Task Schema Version。
29. Task / Attempt / Retry / Queue / Dead Letter 必须完整可观测。
30. 本设计遵守 04 Unified Communication、14 Observability、15 Deployment、21 Security、22 Feedback、23 Diagnostics、24 Testing。

---

## 124. 最终模型

```text
Client / Domain
      │
      ▼
Create Task Command
      │
      ▼
PostgreSQL
Task = Source of Truth
      │
      ├── Outbox
      │
      ▼
Queue / Event Bus
      │
      ▼
Worker Pool
      │
      ▼
Claim + Lease + Fencing
      │
      ▼
Task Attempt
      │
      ├── Success
      ├── Retry
      ├── Wait For User
      ├── Partial Success
      ├── Failure
      └── Cancel
      │
      ▼
PostgreSQL Task State
      │
      ├── Query
      ├── Event
      └── Stream
      │
      ▼
Client / Operations
```

最终边界：

> Task 是持久业务对象，Attempt 是一次可失效的执行租约，Queue 只是触发器，Worker 只是执行者。系统通过 At-least-once + Idempotency + Lease + Fencing + Reconciliation 获得可恢复的后台执行，而不是依赖某个进程、某条 Queue Message 或某个 WebSocket 永远不出错。
