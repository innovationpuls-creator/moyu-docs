# Application Logging & Diagnostics Design

## 1. 目标

本设计定义系统的应用日志、请求关联、客户端诊断、跨服务 Trace、业务事件诊断、错误记录、敏感信息脱敏、日志保留、调试视图和问题定位方法。

本模块解决：

> 当用户说“我刚才保存失败了”“AI 一直转圈”“评论没有通知”“文档突然只读”“导出卡住”时，开发和运维人员如何从前端错误一路追踪到 Gateway、Domain Service、PostgreSQL、Event、Worker、Provider，并知道到底在哪一层失败，而不是翻一堆互不关联的日志。

---

## 2. 与 Observability 的关系

`14-Observability-Operations-Design` 定义系统总体：

```text
Logs
Metrics
Traces
Audit
Health
Alerts
Runbooks
```

本设计专门细化：

```text
Application Log
Client Diagnostic
Error Correlation
Request / Event / Task Chain
Developer Troubleshooting
```

---

## 3. 五类信息严格分离

```text
Application Log
= 开发排障

Trace
= 跨模块调用链

Metric
= 趋势与容量

Audit
= 高风险行为证据

Client Telemetry
= 浏览器运行情况
```

禁止混成一类。

---

## 4. Correlation Identity

系统统一使用：

```text
requestId
idempotencyKey（如适用）
traceId
eventId
taskId
operationId
sessionId
subscriptionId
deliveryId
resourceId
workspaceId
userId
clientVersion
```

根据上下文选择。

---

## 5. requestId / idempotencyKey

```text
requestId
```

表示：

> 一次具体 Client Command / Query / transport attempt。

真正发生网络重试时，每个 attempt 使用新的 `requestId`。

```text
idempotencyKey
```

表示：

> 一个允许安全重试的逻辑 Mutating Command identity。

因此：

```text
logical retry
→ same idempotencyKey
→ new requestId per attempt
```

日志与 Trace 必须能同时按二者检索，而不是把两种身份混为一个字段。

---

## 6. traceId

```text
traceId
```

表示：

> 一条跨服务执行链。

例如：

```text
Client
↓
Gateway
↓
History Service
↓
PostgreSQL
↓
Outbox
```

---

## 7. eventId

```text
eventId
```

表示：

> 一个已经发生并被发布的业务事件。

Event 被多个 Consumer 消费时：

```text
eventId 不变
trace 可继续关联
```

---

## 8. taskId

```text
taskId
```

表示：

> 一个长生命周期异步任务。

Task 可以跨：

```text
多个 request
多个 worker attempt
多个 trace
```

因此：

```text
taskId ≠ traceId
```

---

## 9. operationId

用于：

```text
multi-resource apply
bulk import
history restore
purge
```

等多阶段业务 Operation。

---

# Part A: Structured Logging

## 10. 日志必须结构化

禁止长期依赖：

```text
print("something happened")
```

统一字段建议：

```text
timestamp
level
service
environment
version
operation
message
requestId
traceId
result
errorCode
durationMs
```

按上下文追加：

```text
userId
workspaceId
projectId
resourceId
taskId
eventId
deliveryId
provider
```

---

## 11. Log Level

统一：

```text
DEBUG
INFO
WARN
ERROR
```

---

## 12. DEBUG

用于：

```text
开发 / 受控诊断
```

生产默认不能无限记录高频 DEBUG。

---

## 13. INFO

用于：

```text
重要生命周期
Task 状态
部署版本
业务操作完成
```

不记录每个字符输入。

---

## 14. WARN

用于：

```text
可恢复异常
retry
fallback
degraded
slow dependency
```

---

## 15. ERROR

用于：

```text
当前操作失败
unexpected exception
data inconsistency
provider hard failure
```

---

# Part B: 禁止日志内容

## 16. 永不记录

普通日志禁止：

```text
Password
Session Credential
Authorization Header
Cookie
OAuth Code
Access Token
Refresh Token
Provider Secret
Webhook Secret
Reset Token
Verification Token
Signed URL 完整值
Encryption Key
```

---

## 17. 正文内容

默认不记录：

```text
完整 Resource Content
完整 Comment
完整 AI Prompt
完整 AI Context
完整 Uploaded File Content
```

---

## 18. 必要调试

如果极端问题需要内容级调试：

```text
受控开启
最小采样
脱敏
短期保留
权限隔离
明确原因
```

不能成为默认生产日志。

---

# Part C: Frontend Logging

## 19. Client Telemetry

浏览器可上报：

```text
uncaught error
unhandled promise rejection
editor crash
realtime disconnect
sync failure
offline storage failure
task stream failure
route load failure
performance sample
```

---

## 20. Frontend Context

客户端诊断至少带：

```text
clientVersion
route / feature
requestId
resourceId（如适用）
taskId（如适用）
network state
realtime state
```

---

## 21. 不上传敏感值

浏览器 Telemetry 不能上传：

```text
Password
Token
完整正文
完整 Comment
完整 Prompt
```

---

## 22. Client Error Fingerprint

相同错误可通过：

```text
error type
stack fingerprint
client version
feature
```

聚类。

避免每次错误都成为独立噪音。

---

# Part D: Request Diagnostics

## 23. 一次 Command

例如：

```text
RenameResource
```

完整日志链：

```text
Client requestId=R1
↓
Gateway traceId=T1
↓
Resource Service
↓
Permission Check
↓
PostgreSQL Transaction
↓
Outbox
↓
ResourceRenamed eventId=E1
```

---

## 24. Query Diagnostics

Query 日志重点：

```text
operation
scope
duration
result count
cache hit / miss
permission result
error
```

不记录完整返回正文。

---

## 25. Command Diagnostics

Command 日志重点：

```text
operation
actor
target
validation result
permission result
transaction result
idempotency result
duration
```

---

# Part E: Async Task Diagnostics

## 26. Task Timeline

每个 Task 需要可重建：

```text
Created
Queued
Dequeued
Running
Retrying
Succeeded / Failed
```

---

## 27. Attempt

每次 Worker 执行：

```text
attemptId
```

或等价标识。

Task 重试时：

```text
taskId 相同
attempt 不同
```

---

## 28. Task Diagnostic

Task 至少可查：

```text
taskId
type
state
createdAt
startedAt
finishedAt
attempt count
current worker
last errorCode
retryable
target resources
related trace
```

---

## 29. Queue Diagnostic

需要：

```text
queue
enqueue time
dequeue time
wait duration
attempt
dead letter state
```

---

# Part F: Event Diagnostics

## 30. Event Publish

记录：

```text
eventId
type
version
producer
traceId
aggregate / resource scope
publish result
```

---

## 31. Event Consume

Consumer 记录：

```text
eventId
consumer
attempt
dedup result
processing duration
result
```

---

## 32. 重复 Event

如果重复 Event 被安全去重：

```text
INFO / DEBUG
```

不应成为 ERROR。

---

## 33. Event Lag

至少可以计算：

```text
event created
→ consumer processed
```

之间 Lag。

---

# Part G: Realtime Diagnostics

## 34. Realtime Connection

记录：

```text
connection open
connection close
close reason
session identity
client version
gateway instance
```

不记录每一个字符 Update。

---

## 35. Subscription

关键生命周期：

```text
subscribe
subscription rejected
permission downgrade
unsubscribe
session replaced
```

可以记录。

---

## 36. Yjs Update 日志

禁止生产常态记录：

```text
每个 Yjs Update Payload
```

只记录聚合指标：

```text
update count
bytes
durable lag
merge error
resource hotspot
```

---

## 37. Resource Diagnostic View

按：

```text
resourceId
```

应能看到：

```text
lifecycle
active session
realtime worker
subscription count
persistence status
durable lag
checkpoint
recent errors
permission changes
search lag
related tasks
```

不暴露正文。

---

# Part H: Database Diagnostics

## 38. PostgreSQL Log

应用日志记录：

```text
query category
duration
transaction result
retry
deadlock
timeout
connection wait
```

不默认记录完整 SQL 参数。

---

## 39. Slow Query

慢 Query：

```text
operation
normalized query fingerprint
duration
rows
plan reference（按工具）
```

用于优化。

---

## 40. Transaction

高价值 Transaction：

```text
begin
commit / rollback
errorCode
duration
```

可通过 Trace Span 表达，不要求每次写大量 Log。

---

# Part I: Provider Diagnostics

## 41. Provider Call

记录：

```text
provider
operation
duration
result
normalized error
retry attempt
circuit state
```

---

## 42. Provider 原始错误

Provider 原始错误：

```text
可进入受控 diagnostic field
```

但必须：

```text
脱敏
```

不能直接原样写日志。

---

# Part J: Error Catalog

## 43. Error Code

每个可预期错误必须有：

```text
stable errorCode
```

例如：

```text
SESSION_REPLACED
PERMISSION_DENIED
RESOURCE_TRASHED
COMMENT_ANCHOR_DETACHED
AI_CHANGESET_CONFLICT
PROVIDER_UNAVAILABLE
```

---

## 44. Error Code 稳定性

前端逻辑依赖：

```text
errorCode
```

而不是：

```text
message string
```

---

## 45. Internal Exception

未知 Exception：

```text
映射 INTERNAL_ERROR
```

内部保存：

```text
exception type
stack
traceId
```

---

# Part K: Diagnostic Flow

## 46. 用户报告问题

标准排障入口：

```text
requestId
taskId
resourceId
approximate time
clientVersion
```

---

## 47. 示例：History Restore 失败

```text
Frontend
requestId=R1
↓
Gateway traceId=T1
↓
History Restore Command
↓
Operation operationId=O1
↓
PostgreSQL
↓
Worker taskId=K1
↓
Failure errorCode=...
```

可以完整追踪。

---

## 48. 示例：评论没通知

```text
Comment Command
↓
Comment Commit
↓
Outbox
↓
CommentMentioned eventId=E1
↓
Notification Consumer
↓
Notification Created / Failed
```

从 eventId 可查问题停在哪。

---

## 49. 示例：AI 一直 Running

```text
taskId
↓
queue
↓
attempt
↓
worker heartbeat
↓
provider call
↓
retry / timeout
```

不需要靠猜。

---

# Part L: Diagnostic UI / Operations

## 50. Internal Diagnostic View

运维 / 开发可有：

```text
Request Lookup
Task Lookup
Resource Lookup
Event Lookup
Delivery Lookup
```

---

## 51. Request Lookup

输入：

```text
requestId
```

得到：

```text
trace
service chain
result
errorCode
duration
```

---

## 52. Task Lookup

输入：

```text
taskId
```

得到：

```text
state
attempt
queue wait
worker
related resources
provider calls
error
```

---

## 53. Resource Lookup

输入：

```text
resourceId
```

只显示技术状态。

不能默认显示正文。

---

# Part M: Retention

## 54. 日志保留

不同类型独立 Retention：

```text
Application Log
Client Telemetry
Trace
Metric
Audit
Security Incident
```

---

## 55. DEBUG Retention

DEBUG：

```text
短期
低采样
```

---

## 56. Audit Retention

Audit：

```text
更长
独立访问控制
```

不能和普通应用日志一起自动短期清理。

---

# Part N: Sampling

## 57. Trace Sampling

高流量：

```text
可以采样
```

但：

```text
ERROR
High-risk operation
Security incident
```

应提高采样率或强制保留。

---

## 58. Log Sampling

高频重复日志：

```text
可以 rate limit / sample
```

避免日志系统本身拖垮生产。

---

# Part O: PII / Privacy

## 59. User ID

内部：

```text
userId
```

可用于诊断。

但日志平台访问：

```text
必须受控
```

---

## 60. Email / IP

Email、IP：

```text
属于敏感信息
```

应：

```text
mask / restricted field
```

按需要保留。

---

## 61. Search Query

用户 Search Query 可能包含敏感内容。

默认不应无限长期全文保留。

---

# Part P: Frontend Feedback Logging

## 62. Client State Transition

重要系统状态可以上报：

```text
Online → Offline
Reconnecting → Synced
Authenticated → SessionReplaced
Editable → ReadOnly
Task Running → Failed
```

用于定位体验问题。

---

## 63. 不记录 UI 噪音

禁止把：

```text
hover
mouse move
每次 selection
每个 keystroke
```

当生产日志。

---

# Part Q: Release Diagnostics

## 64. Version Correlation

所有日志 / Trace 至少关联：

```text
service version
client version
deployment environment
```

便于发现：

```text
某版本上线后错误激增
```

---

## 65. Feature Flag

发生错误时尽量记录：

```text
relevant feature flag variant
```

但避免高基数乱标。

---

# Part R: Alert Integration

## 66. ERROR 不等于 Alert

单条 ERROR：

```text
不一定需要叫醒人
```

Alert 应基于：

```text
rate
impact
duration
criticality
```

---

## 67. Security Error

以下可更敏感：

```text
auth anomaly
permission bypass attempt
secret failure
mass export
webhook signature spike
```

---

# Part S: Hard Constraints

## 68. 架构硬约束

1. Application Log、Trace、Metric、Audit、Client Telemetry 必须分离。
2. 全系统必须统一 requestId / idempotencyKey / traceId / eventId / taskId 等关联标识，并保持各自生命周期语义。
3. 前端错误必须能够通过 requestId 与后端诊断关联。
4. 异步 Task 必须能重建完整状态 Timeline。
5. Event Producer / Consumer 必须记录 eventId。
6. Realtime 不允许逐字符写生产日志。
7. 普通日志不得包含 Password / Token / Secret /完整敏感正文。
8. Provider 原始响应必须脱敏后才能进入诊断。
9. Error Code 必须稳定，前端不能依赖 message 字符串做逻辑。
10. Resource Diagnostic 默认只展示技术状态，不展示正文。
11. 日志与 Trace 必须带部署版本。
12. 高流量日志必须支持 Sampling / Rate Limit。
13. Audit 必须独立 Retention 与权限。
14. 日志系统故障不能阻塞核心业务。
15. Client Telemetry 故障不能阻塞前端。
16. 本设计与 14、22 号设计保持一致。

---

## 69. 最终模型

```text
Frontend
requestId=R1
   │
   ▼
Gateway
traceId=T1
   │
   ▼
Domain Service
   │
   ├── PostgreSQL
   │
   └── Outbox
          │
          ▼
      eventId=E1
          │
          ▼
        Worker
          │
          ▼
      taskId=K1 / deliveryId=D1
```

排障：

```text
用户报告
↓
requestId / taskId / resourceId
↓
Trace
↓
Logs
↓
Event / Worker
↓
Provider / PostgreSQL
↓
Root Cause
```

系统必须保证：

> 一次用户操作无论跨多少服务、Event、Worker 或外部 Provider，都能通过稳定关联标识还原出发生了什么，同时不会为了“好排障”把密码、Token、正文和其他敏感数据倾倒进日志系统。
