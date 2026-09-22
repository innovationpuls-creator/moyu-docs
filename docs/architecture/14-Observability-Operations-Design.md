# Observability & Operations Design

## 1. 目标

本设计定义系统统一的可观测性与运维能力。

本模块解决：

> 当系统由 Realtime、Persistence、Permission、History、Search、Asset、AI、Import / Export 等多个模块共同工作时，如何快速知道“系统现在是否健康、哪里变慢了、哪里失败了、影响了谁、为什么失败、如何恢复”，并让生产运维具备稳定、可追踪、可审计、可自动告警和可恢复的基础能力。

本设计按可上线产品标准设计。

Observability 不是：

```text
到处 print
出问题以后 SSH 上服务器看日志
每个服务自己定义一套监控
```

而是系统级基础设施。

---

## 2. 核心组成

统一 Observability 至少包括：

```text
Logs
Metrics
Traces
Events
Audit
Health
Alerts
Dashboards
Runbooks
Operational Actions
```

其中：

```text
Logs
= 发生了什么

Metrics
= 系统整体表现如何

Traces
= 一次请求经过了哪些模块

Audit
= 谁执行了什么敏感操作

Alerts
= 哪些异常需要人工或自动处理

Runbooks
= 出现异常以后怎么恢复
```

---

## 3. 统一可观测性上下文

所有核心模块必须共享统一上下文。

至少能够关联：

```text
requestId
traceId
userId
workspaceId
projectId
resourceId
taskId
subscriptionId
service
operation
```

不是所有字段每次都必须存在。

但一旦业务链中存在：

```text
resourceId
taskId
traceId
```

就应尽量向下游传播。

---

## 4. TraceId

`traceId` 表示：

> 一次跨模块业务链。

例如：

```text
User
↓
Start AI Task
↓
Search
↓
Permission
↓
Resource Read
↓
Model
↓
ChangeSet
↓
Apply
↓
Persistence
↓
History
```

整个链路应该能通过：

```text
traceId
```

串起来。

---

## 5. RequestId / IdempotencyKey

`requestId` 表示：

> 一次具体网络请求 / Command attempt。

每次真正的重试 attempt 使用新的 `requestId`，方便日志和 Trace 区分。

`idempotencyKey` 表示：

> 一个允许安全重试的逻辑 Command identity。

例如同一个 `ApplyChangeSet` 因网络超时重试：

```text
idempotencyKey = same
requestId = new per attempt
```

不能再用同一个字段同时表达“网络请求实例”和“业务幂等身份”。

---

## 6. Resource / Task Correlation

生产排障必须能够回答：

```text
某个 resourceId 最近发生了什么？
某个 taskId 为什么失败？
某个 workspace 是否出现集中异常？
```

因此关键日志、Trace 和 Metrics 必须能关联到：

```text
resourceId
taskId
workspaceId
```

但需要控制 Metrics Cardinality，不能把高基数字段无脑做成 Metric Label。

---

## 7. Logs

日志必须使用：

```text
Structured Log
```

而不是只输出不可解析自然语言。

至少应具备：

```text
timestamp
level
service
operation
message
requestId / traceId
result
errorCode
duration
```

必要时增加业务上下文。

---

## 8. Log Level

统一使用：

```text
DEBUG
INFO
WARN
ERROR
```

严重程度通过 Alert / Incident Severity 表达，不再增加 `FATAL` 作为第五套应用日志 Level。各模块不得自行发明 Level。

生产环境：

```text
DEBUG
```

默认不应无限开启。

---

## 9. INFO

`INFO` 用于：

- 重要生命周期变化
- 关键 Task 状态变化
- 服务启动 / 关闭
- 正常但有诊断价值的业务操作

不应记录：

```text
每个字符输入
每条 Awareness
每条 Yjs Update 全内容
```

否则日志量会失控。

---

## 10. WARN

`WARN` 用于：

```text
系统仍然能够继续工作
但出现需要关注的异常或降级
```

例如：

```text
Search 索引延迟升高
AI Provider 发生 Retry
Persistence Checkpoint 暂时失败
缓存失效传播变慢
```

---

## 11. ERROR

`ERROR` 表示：

```text
一个操作或业务结果已经失败
```

例如：

```text
ApplyChangeSet Failed
Asset Scan Failed
Permission Event Propagation Failed
Persistence Journal Write Failed
```

ERROR 必须包含：

```text
errorCode
traceId / requestId
operation
```

以及必要错误上下文。

---

## 12. Error Stack

内部 ERROR 可以记录：

```text
stack trace
dependency error
internal exception
```

但必须进入受控内部日志。

不能直接把完整 Stack 返回客户端。

---

## 13. 敏感数据禁止进入日志

默认禁止记录：

```text
password
access token
refresh token
signed URL full token
share token
invitation token
private key
database password
object storage secret
完整正文
完整 AI prompt
完整用户上传文件
```

如果确有诊断需要：

```text
使用受控 Debug / Sampling
+
脱敏
+
短期保留
```

---

## 14. PII / Content Redaction

日志系统必须支持：

```text
Redaction
```

至少对：

```text
email
token
authorization header
cookie
query secret
file secret
```

进行脱敏。

正文内容默认不进入普通日志。

---

## 15. Log Sampling

高频路径允许 Sampling。

例如：

```text
Realtime heartbeat
successful search query
successful asset download
```

可以采样。

但不能采样掉：

```text
安全事件
关键错误
权限拒绝
持久化失败
永久删除
Owner Transfer
```

---

## 16. Metrics

系统 Metrics 至少分为：

```text
Traffic
Latency
Errors
Saturation
Business Health
```

所有核心模块都需要自己的健康指标。

---

## 17. Traffic

需要知道：

```text
request rate
active websocket
active resource session
active subscription
yjs update rate
search query rate
asset upload rate
ai task rate
import / export rate
```

---

## 18. Latency

至少关注：

```text
API latency
permission check latency
realtime fanout latency
persistence durable latency
history preview latency
search latency
asset upload complete latency
AI queue wait
AI task duration
import / export duration
```

---

## 19. Errors

至少监控：

```text
5xx
4xx
permission denied
journal failure
checkpoint failure
search failure
asset processing failure
AI provider failure
task failure
dead letter growth
reconciliation failure
```

---

## 20. Saturation

至少监控：

```text
CPU
memory
event loop / thread pool saturation
connection pool
database pool
queue depth
worker concurrency
disk
object storage error
message broker lag
AI provider capacity
```

---

## 21. Business Health

除了基础设施指标，还必须有：

```text
active resource sessions
durable lag
index lag
permission propagation lag
AI partial apply count
asset orphan count
failed import item count
history restore failure
trash / purge backlog
dead letter count
```

这些才真正反映产品是否正常工作。

---

## 22. 高基数控制

以下字段通常不应该直接作为 Metrics Label：

```text
userId
resourceId
taskId
requestId
full URL
file name
search query
```

因为会造成：

```text
Metric Cardinality Explosion
```

这些信息应进入：

```text
Logs / Traces
```

Metrics 只保留低基数维度。

---

## 23. 推荐低基数 Label

适合 Metrics Label：

```text
service
operation
resourceType
status
errorCode
region
provider
taskType
result
```

具体数量仍需控制。

---

## 24. Traces

跨模块调用必须支持：

```text
Distributed Tracing
```

至少覆盖：

```text
API
Command
Query
Event
Async Task
External Dependency
```

Realtime 高频单帧不要求全部产生完整 Trace。

---

## 25. Span

一个 Trace 可以包含：

```text
HTTP Request
Permission Check
Database Query
Event Publish
Search Query
Model Call
Asset Storage Call
Apply Resource Change
```

每个 Span 至少记录：

```text
operation
duration
status
service
```

---

## 26. 异步 Trace

Task / Event 不是同步调用链。

系统仍需要把：

```text
Parent Trace
↓
Async Event / Task
```

关联起来。

例如：

```text
StartImport
↓
Queue
↓
Worker
↓
CreateResource
```

不能因为进入 Queue 就完全失去 Trace。

---

## 27. Event Trace

Event 至少应保留：

```text
eventId
traceId
producer
consumer
eventType
eventVersion
```

用于：

- 延迟分析
- 消费失败
- 重复投递
- Dead Letter
- 跨服务排障

---

## 28. Async Task Trace

AI、Import、Export、History Restore、Reindex 等长任务：

```text
taskId
```

是长期操作身份。

Trace 可以跨多个 Attempt。

因此：

```text
taskId
≠
traceId
```

一个 Task 可以产生多个 Trace。

---

## 29. Audit 与 Log 分离

Audit 不是普通应用日志。

Audit 需要更高可靠性和更严格访问控制。

例如：

```text
PermissionChanged
OwnerTransferred
ShareCreated
ShareRevoked
ResourcePermanentlyDeleted
WorkspaceDeletionRequested
SensitiveExport
AI High Risk Apply
```

属于 Audit。

---

## 30. Audit 目标

Audit 回答：

```text
谁
在什么时候
对什么对象
执行了什么
结果如何
```

用于：

- 安全调查
- 管理
- 合规
- 高风险操作追踪

---

## 31. Audit 不依赖普通日志保留

即使普通日志：

```text
7 天后删除
```

Audit 仍可以按自己的 Retention 长期保存。

Audit 与 Logs 有不同生命周期。

---

## 32. Audit 防篡改

生产级 Audit 应避免：

```text
普通业务服务随意修改历史 Audit
```

应使用：

```text
append-oriented
restricted write path
tamper-evident strategy
```

或等价方案。

具体产品栈由 `26-Technology-Stack-Decision.md` 固定为 OpenTelemetry + Prometheus + Grafana + Loki + Tempo；Audit 仍保持独立权威存储与访问控制。

---

## 33. Audit 访问权限

只有授权管理者可以查看安全 Audit。

普通用户不能：

```text
读取整个 Workspace 的安全事件
```

Audit 查询本身也应进入 Audit。

---

## 34. Audit 内容最小化

Audit 不记录不必要正文。

例如：

```text
User A changed User B from Edit to Read
```

足够。

不需要同时存整个 Resource Content。

---

## 35. Health Check

服务必须提供至少：

```text
Liveness
Readiness
```

两类健康检查。

---

## 36. Liveness

Liveness 表示：

> 这个服务进程是否仍然存活并能够继续运行。

Liveness 不应该因为：

```text
Search dependency 临时失败
```

就把主服务无限重启。

---

## 37. Readiness

Readiness 表示：

> 当前实例是否可以接收新流量。

例如：

```text
数据库连接完全不可用
必要 Schema 未加载
关键配置不存在
```

可以让：

```text
Readiness = false
```

停止新流量进入。

---

## 38. Dependency Health

系统需要区分：

```text
Critical Dependency
Degradable Dependency
```

例如：

### Critical

```text
Primary Database
Permission Source
Persistence Journal Storage
```

### Degradable

```text
Search
AI Provider
Analytics
Preview Worker
```

依赖故障不应该全部导致整个系统不健康。

---

## 39. Degraded State

模块必须能够显式暴露：

```text
Healthy
Degraded
Unavailable
```

例如：

```text
Search = Unavailable
Realtime = Healthy
Persistence = Healthy
```

产品仍然可以继续编辑。

---

## 40. SLI

系统必须定义：

```text
Service Level Indicator
```

至少包括：

```text
availability
latency
durability
freshness
queue delay
error rate
```

不同模块使用不同 SLI。

---

## 41. SLO

生产环境应为核心路径定义：

```text
Service Level Objective
```

例如：

```text
Realtime availability
Durable write success
Permission check availability
Search freshness
AI task completion
```

本设计不写死具体百分比。

实际 SLO 根据：

```text
产品等级
部署成本
压测
用户规模
```

确定。

---

## 42. Error Budget

有 SLO 后应有：

```text
Error Budget
```

用于判断：

```text
当前是否还能继续激进发布
还是应该优先修稳定性
```

这属于成熟运维流程。

第一版可以先建立框架，不要求一开始就复杂自动化。

---

## 43. 核心主链

最重要的健康链路是：

```text
User Edit
↓
Realtime
↓
Yjs
↓
Persistence Durable
```

至少需要能够测量：

```text
edit accepted
durable success
durable latency
session health
disconnect rate
reconnect rate
```

---

## 44. Durable Lag

Persistence 必须暴露：

```text
Durable Lag
```

表示：

> 已接受内容变化距离可靠持久化还差多少时间 / 数据。

这是核心安全指标。

Durable Lag 异常升高必须触发告警。

---

## 45. Permission Propagation Lag

Permission 模块必须暴露：

```text
Permission Propagation Lag
```

表示：

```text
权限变化
↓
所有相关 Realtime / AI / Plugin 实例失效旧授权
```

的传播时间。

这是安全指标，不只是性能指标。

---

## 46. Search Index Lag

Search 必须暴露：

```text
Index Lag
```

表示：

```text
Source Current State
vs
Search Indexed State
```

之间延迟。

---

## 47. Event Consumer Lag

所有关键消费者都需要监控：

```text
Consumer Lag
Queue Depth
Oldest Pending Age
```

不能只看：

```text
Queue 有多少条
```

还要看：

```text
最老一条已经等了多久
```

---

## 48. Dead Letter

Dead Letter / Failed Task 必须成为一级运维对象。

运维界面至少需要知道：

```text
type
count
oldest age
last error
affected scope
retryable
```

不能让 Dead Letter 成为“消息坟场”。

---

## 49. Reconciliation Health

Search、Asset Reference、Permission Cache、History Index 等存在 Reconciliation。

必须监控：

```text
last successful reconciliation
items checked
items repaired
repair failure
```

防止：

```text
Reconciliation Worker 早就死了
但没人知道
```

---

## 50. Alert

Alert 只针对：

```text
需要行动
```

的异常。

不能把：

```text
所有 WARN
```

都变成 Pager。

否则会产生 Alert Fatigue。

---

## 51. Alert Severity

建议统一：

```text
P1 Critical
P2 High
P3 Medium
P4 Low
```

或等价等级。

重点是全系统统一。

---

## 52. P1

P1 适合：

```text
大范围无法编辑
大范围数据无法持久化
严重权限绕过
大规模数据泄漏风险
Primary 数据不可用
```

需要立即响应。

---

## 53. P2

P2 适合：

```text
部分核心功能严重退化
高 Durable Lag
Permission Propagation Lag 超阈值
大规模 Task Failure
```

需要快速处理。

---

## 54. P3 / P4

适合：

```text
Search 轻度延迟
非核心 Worker 积压
部分 Preview 失败
容量接近阈值
```

通常工作时间处理。

---

## 55. Alert Dedup

同一根因不能：

```text
产生 500 条独立告警
```

告警系统应支持：

```text
Dedup
Grouping
Silence
Maintenance Window
```

---

## 56. Alert 必须可行动

好的 Alert 应包含：

```text
发生了什么
影响范围
当前指标
相关 Dashboard
相关 Runbook
trace / log 入口
```

不能只有：

```text
ERROR RATE HIGH
```

---

## 57. Dashboard

至少需要：

```text
System Overview
Realtime
Persistence
Permission
Search
Asset
AI
Import / Export
Queue / Event
Database
Infrastructure
Security
```

等 Dashboard。

---

## 58. System Overview Dashboard

首页至少展示：

```text
overall availability
request error rate
active users / sessions
realtime disconnect
durable lag
permission lag
search lag
queue depth
AI backlog
storage health
```

用于快速判断系统是否整体健康。

---

## 59. Resource Diagnostic View

运维工具建议支持：

```text
按 resourceId 查询
```

看到：

```text
lifecycle
current session
persistence state
last checkpoint
durable status
permission state summary
search index state
history state
recent errors
recent tasks
```

不直接展示全部正文。

---

## 60. Task Diagnostic View

按：

```text
taskId
```

查看：

```text
task type
status
attempts
queue time
worker
last error
affected resources
trace
retryability
```

适用于：

```text
AI
Import
Export
Reindex
History Restore
Purge
```

---

## 61. User Diagnostic View

支持按：

```text
userId
```

查看：

```text
recent login / session summary
recent failed permission checks
recent task failures
recent affected resources
```

但访问必须严格限制。

不能让普通运维随意浏览用户正文。

---

## 62. Workspace Diagnostic View

支持按：

```text
workspaceId
```

查看：

```text
resource count
storage usage
active sessions
task backlog
quota
recent incidents
failed operations
```

适合排查某一租户异常。

---

## 63. Operations Console

生产环境建议提供：

```text
Operations Console
```

用于受控执行运维动作。

例如：

```text
Retry Failed Task
Replay Dead Letter
Trigger Reindex
Trigger Reconciliation
Close Broken Session
Invalidate Cache
Rebuild Search Entry
Retry Asset Processing
```

---

## 64. 运维动作不能直接改数据库

Operations Console 不应把：

```text
直接 SQL UPDATE
```

当正常产品运维方式。

运维动作应该调用：

```text
正式 Command / Admin Operation
```

从而保留：

- Permission
- Validation
- Audit
- Idempotency
- Trace

---

## 65. Break Glass

极端事故下可以设计：

```text
Break Glass
```

高权限紧急操作。

要求：

```text
强认证
最小授权
明确理由
自动过期
完整 Audit
高风险告警
```

不能使用共享 Root 密码。

---

## 66. Feature Flag

生产系统需要统一：

```text
Feature Flag
```

用于：

- 灰度功能
- 快速关闭问题功能
- Provider 切换
- 新协议上线
- 实验

Flag 不应散落在代码中成为无管理状态。

---

## 67. Kill Switch

高风险模块建议有：

```text
Kill Switch
```

例如：

```text
AI Apply
Large Import
Public Share
New Resource Type
```

发生严重问题时可以快速关闭新增操作。

关闭某功能不能破坏已存在 Resource 的基本访问。

---

## 68. Dynamic Config

可安全动态调整：

```text
rate limit
worker concurrency
task queue cap
feature flag
timeout
sampling
```

但高风险配置变化需要：

```text
validation
audit
rollback
```

---

## 69. Config Version

生产配置需要：

```text
version
```

或等价审计能力。

出现事故时必须知道：

```text
当时系统到底用了哪套配置
```

---

## 70. Release Correlation

Logs / Traces / Metrics 必须能够关联：

```text
service version
build version
release id
```

这样可以判断：

```text
错误是否从某次发布以后开始
```

---

## 71. Canary / Rollout Observation

虽然完整 Deployment 在后续模块设计，但 Observability 必须支持：

```text
按 version
按 instance group
按 region
```

比较错误率和延迟。

这样才能安全灰度。

---

## 72. Incident

系统必须建立统一 Incident 流程。

至少包括：

```text
Detect
Triage
Mitigate
Recover
Review
```

---

## 73. Incident Timeline

重大事故应自动或人工记录：

```text
first alert
impact start
mitigation action
service recovery
full recovery
```

用于 Postmortem。

---

## 74. Incident Scope

事故影响至少能够表达：

```text
all users
single region
single service
single workspace
single resource
single provider
```

避免：

```text
某个 Workspace 的 Search 问题
```

被误判成全站事故。

---

## 75. Runbook

每个 P1 / P2 级 Alert 应关联：

```text
Runbook
```

Runbook 至少包括：

```text
症状
确认方法
常见原因
安全缓解方式
回滚方式
升级路径
恢复验证
```

---

## 76. Runbook 不依赖个人经验

不能让核心恢复流程只存在于：

```text
某个工程师脑子里
```

Runbook 必须版本化并与服务共同维护。

---

## 77. Postmortem

重大 Incident 后需要：

```text
Postmortem
```

至少回答：

```text
发生了什么
影响了谁
为什么没有更早发现
怎么恢复
怎么防止复发
```

重点是修系统，不是追责个人。

---

## 78. Capacity Monitoring

生产运维必须监控容量趋势。

至少包括：

```text
database size
object storage
search index size
journal size
queue depth
connection count
worker saturation
AI provider usage
bandwidth
```

---

## 79. Capacity Forecast

不能等：

```text
磁盘 100%
```

才处理。

需要根据趋势提供：

```text
forecast
threshold warning
headroom
```

具体预测方式由运维体系选择。

---

## 80. Connection Monitoring

Realtime 需要特别监控：

```text
active connections
connection create rate
connection close rate
abnormal close
reconnect storm
subscription count
per connection resource count
```

---

## 81. Reconnect Storm

网络或服务抖动可能造成：

```text
大量 Client 同时重连
```

必须监控：

```text
Reconnect Storm
```

并配合：

```text
backoff
jitter
rate control
```

防止恢复时再次把系统打挂。

---

## 82. Resource Hotspot

系统需要能够发现：

```text
单个 Resource
```

产生异常高：

```text
update rate
subscriber count
bandwidth
CPU
```

用于：

- Transport Isolation
- Sharding
- Rate Protection
- Incident 排查

具体热点 ID 不作为永久 Metric Label，可通过 Trace / Log / Top-N 诊断系统实现。

---

## 83. Slow Consumer

Realtime 必须监控：

```text
slow consumer count
queue length
resync count
forced disconnect
```

防止少量慢客户端拖累整体系统。

---

## 84. Persistence Operations

Persistence 运维至少需要：

```text
journal health
checkpoint backlog
checkpoint failure
compaction backlog
restore duration
corruption detection
fallback count
```

---

## 85. Search Operations

Search 运维至少需要：

```text
index lag
failed index task
rebuild status
reconciliation status
query latency
zero result anomaly
schema version
active index
```

---

## 86. Asset Operations

Asset 运维至少需要：

```text
upload failure
processing backlog
scan failure
blocked file
orphan upload
GC backlog
object storage error
CDN error
```

---

## 87. AI Operations

AI 运维至少需要：

```text
queue wait
provider latency
provider error
model timeout
tool error
change set conflict
partial apply
cost / token usage
task cancellation
```

---

## 88. Import / Export Operations

至少：

```text
queue depth
parse failure
conversion failure
sandbox failure
temp storage usage
cleanup backlog
partial import
export failure
result expiry
```

---

## 89. Database Operations

至少监控：

```text
connection pool
query latency
slow query
lock wait
deadlock
replication lag
storage
transaction failure
```

具体数据库产品在 Deployment 设计中决定。

---

## 90. Cache Operations

至少监控：

```text
hit rate
miss rate
eviction
memory usage
error
stale read
invalidation lag
```

缓存失效问题必须可诊断。

---

## 91. Message / Queue Operations

至少：

```text
publish error
consumer error
lag
retry
dead letter
queue depth
oldest message age
throughput
```

---

## 92. External Dependency

所有外部 Provider 需要单独监控：

```text
availability
latency
error
rate limit
quota
```

例如：

```text
Object Storage
CDN
AI Provider
Email
Search Engine
```

---

## 93. Synthetic Check

关键用户路径建议有：

```text
Synthetic Monitoring
```

例如定时验证：

```text
login
create resource
edit
durable
search
download asset
```

避免：

```text
服务指标看起来都绿
但用户流程实际坏了
```

---

## 94. End-to-End Health

至少要有一条：

```text
真实端到端健康检查
```

覆盖：

```text
API
Permission
Resource
Persistence
```

Search / AI 等非核心能力可有独立检查。

---

## 95. Client Observability

前端需要上报必要的：

```text
page crash
uncaught error
websocket reconnect
sync failure
slow render
task stream disconnect
```

但不能：

```text
上传完整文档正文作为 error context
```

---

## 96. Client / Server Correlation

客户端错误应尽量携带：

```text
requestId
traceId
resourceId
```

让前端和后端故障能关联。

---

## 97. Browser Performance

对于编辑器至少关注：

```text
input latency
render latency
large document performance
memory usage
reconnect duration
initial load time
```

这些数据可以采样。

---

## 98. Telemetry Privacy

Telemetry 必须遵守：

```text
data minimization
access control
retention
redaction
```

不能因为“监控”就无限收集用户内容。

---

## 99. Retention

不同 Observability 数据使用不同 Retention。

例如：

```text
high-volume logs
shorter

metrics
medium / long trend

traces
sampled

audit
longer

incident
long-term
```

具体天数由成本与合规决定。

---

## 100. Cold Storage

长期 Audit / Incident 数据可以进入：

```text
Cold Storage
```

降低成本。

普通高频 Debug Log 不需要永久保存。

---

## 101. Access Control

Observability 平台本身必须有权限控制。

例如：

```text
Developer
SRE
Security
Admin
```

可以看到的内容不同。

不能让所有开发人员默认看到：

```text
所有用户敏感 Audit
```

---

## 102. Production Access

生产数据访问应：

```text
least privilege
time bounded
audited
```

避免永久共享高权限账号。

---

## 103. Operations Action Audit

以下运维动作必须 Audit：

```text
replay dead letter
manual reindex
manual reconciliation
force close session
cache invalidate
break glass
manual purge retry
feature flag change
kill switch
```

---

## 104. 自动恢复

部分异常可以自动恢复。

例如：

```text
consumer restart
retry transient dependency
reassign task
reconnect search
```

但必须设置：

```text
retry limit
backoff
circuit breaker
```

防止自动恢复变成无限故障循环。

---

## 105. Self-Healing 边界

允许自动处理：

```text
无副作用的 Worker restart
幂等 Task retry
失效 Cache rebuild
```

不应自动执行：

```text
Permanent Delete
Owner Change
批量数据修复
不可逆 Schema Rewrite
```

高风险恢复需要人工确认。

---

## 106. Operational Reconciliation

运维系统应支持发起：

```text
Search Reindex
Asset Reference Rebuild
Permission Cache Refresh
History Index Repair
```

但这些操作必须通过正式管理 Command。

---

## 107. Data Repair

真正的数据修复必须：

```text
有 Repair Plan
Dry Run
Scope
Audit
Rollback / Recovery Strategy
```

不能靠临时脚本直接改生产库后就结束。

---

## 108. Admin Script

如果确实需要一次性 Admin Script：

必须：

```text
版本控制
Code Review
Dry Run
限 Scope
Audit
结果记录
```

避免“临时脚本文化”。

---

## 109. Schema Migration Observability

数据库 / Search / Event Schema Migration 必须监控：

```text
progress
error
lag
backfill
compatibility
```

不能把 Migration 当成黑盒后台任务。

---

## 110. Feature Rollout Metrics

新功能上线前必须定义：

```text
success metric
failure metric
rollback threshold
```

例如上线新的 AI Apply：

```text
partial apply rate
conflict rate
apply failure
```

必须可观察。

---

## 111. Security Monitoring

至少需要监控：

```text
auth failure spike
permission denial anomaly
share token abuse
invitation abuse
rate limit abuse
malware upload
suspicious export
break glass
admin action
```

---

## 112. Abuse Detection

异常行为可以触发：

```text
Rate Limit
Temporary Block
Security Alert
Manual Review
```

具体风控策略以后独立扩展。

---

## 113. Secret Leak Detection

Logs / Traces 进入存储前应尽可能：

```text
detect / redact common secrets
```

防止：

```text
Authorization Header
API Key
Signed Token
```

被长期保存。

---

## 114. Operational Status Page

如果产品规模需要，可以提供：

```text
Status Page
```

展示：

```text
Realtime
Editing
Search
AI
File Upload
Import / Export
```

当前状态。

外部 Status Page 不暴露内部基础设施细节。

---

## 115. Maintenance

计划维护需要：

```text
Maintenance Window
Notice
Drain
Health Update
```

后续 Deployment 模块定义具体滚动流程。

Observability 负责：

```text
监测维护是否按计划执行
```

---

## 116. Drain

实例下线前：

```text
停止接收新连接 / Task
↓
等待安全中的操作完成
↓
迁移或关闭 Connection
↓
退出
```

运维指标必须能够观察：

```text
drain progress
remaining sessions
remaining tasks
```

---

## 117. Crash Loop

系统必须检测：

```text
Crash Loop
```

避免实例不断启动失败却被当作偶发错误。

Crash Loop 应触发高优先级 Alert。

---

## 118. Clock

日志和 Trace 依赖时间。

所有生产实例必须使用可靠时钟同步。

但业务正确性不能完全依赖：

```text
不同机器时间绝对一致
```

事件顺序仍优先使用业务版本 / sequence / causal state。

---

## 119. Timezone

内部时间统一使用：

```text
UTC
```

或等价统一标准。

用户 UI 再转换到本地时区。

避免日志跨服务时区混乱。

---

## 120. 告警抑制与维护窗口

发布、演练、维护时：

```text
不能简单关闭所有监控
```

应使用：

```text
Silence
Maintenance Window
Expected Degradation
```

保留真实异常检测能力。

---

## 121. Chaos / Failure Exercise

成熟阶段建议定期演练：

```text
Search Down
AI Provider Down
Object Storage Slow
Queue Delay
Single Node Failure
Reconnect Storm
```

验证：

```text
降级是否真的有效
Runbook 是否可用
Alert 是否准确
```

不要求第一版立即自动化 Chaos Platform。

---

## 122. Observability Schema

统一日志、Trace、Metric 命名必须有规范。

例如：

```text
service.operation.duration
service.operation.errors
queue.depth
task.duration
```

不能每个团队自己命名：

```text
latency_ms
request_time
cost_time
time_used
```

导致 Dashboard 无法复用。

---

## 123. Naming Version

Observability Event / Audit Schema 也需要版本控制。

尤其当：

```text
字段含义
Error Code
Audit Event
```

发生变化时，要保证旧查询和告警仍可理解。

---

## 124. Error Code Catalog

系统需要统一：

```text
Error Code Catalog
```

至少记录：

```text
code
meaning
retryable
severity
owner module
user message mapping
```

这样：

```text
日志
客户端
告警
Runbook
```

使用同一错误语义。

---

## 125. Ownership

每个服务 / 模块必须有：

```text
Operational Owner
```

至少知道：

```text
谁负责
Runbook 在哪
Dashboard 在哪
哪些 Alert 属于它
```

不是要求固定某个人，而是明确责任边界。

---

## 126. Service Catalog

建议维护：

```text
Service Catalog
```

至少包含：

```text
service
owner
dependencies
criticality
SLO
dashboard
runbook
repo / module
```

随着系统模块增加，这会极大降低排障成本。

---

## 127. 第一版必须具备

第一版上线前至少具备：

```text
Structured Logs
统一 Error Code
Request / Trace Correlation
Core Metrics
Distributed Trace
Liveness / Readiness
Core Dashboards
P1 / P2 Alerts
Dead Letter Visibility
Task Diagnostics
Resource Diagnostics
Audit
Log Redaction
Basic Runbooks
Release Version Correlation
Capacity Monitoring
```

---

## 128. 第一版不要求过度建设

第一版不要求：

```text
自研 Observability Platform
自研 Trace Backend
自研 Metrics Database
复杂 AI Ops Copilot
全自动 Incident Commander
全自动 Chaos Platform
超复杂 AIOps
```

优先采用成熟基础设施。

---

## 129. 核心验收场景

### 场景 1：某 Resource 无法编辑

用户报告：

```text
resourceId = X
```

运维可以通过 Resource Diagnostic View 快速看到：

```text
Lifecycle
Permission
Realtime Session
Persistence
Recent Error
Trace
```

而不是在所有服务日志中人工 grep 数小时。

---

### 场景 2：Persistence 延迟

Durable Lag 持续升高。

结果：

- Dashboard 明确显示
- P2 / P1 告警按影响触发
- Runbook 能定位 Journal / Storage / Worker
- Realtime 仍可根据设计进入 Degraded 保护

---

### 场景 3：Search 故障

Search Engine 宕机。

结果：

```text
Search = Unavailable
Realtime = Healthy
Persistence = Healthy
```

系统 Overview 不把整站直接标红成“全部不可用”。

---

### 场景 4：Permission 传播异常

User 被移除后：

```text
Server B
```

很久仍未失效权限。

结果：

```text
Permission Propagation Lag
```

触发安全 Alert。

可以通过 Trace / Event Consumer Lag 找到传播链问题。

---

### 场景 5：AI Task 失败

用户提供：

```text
taskId
```

运维可以看到：

```text
queue wait
attempt
provider
tool call
last error
affected Resource
trace
```

不需要查看用户完整 Prompt。

---

### 场景 6：Partial Apply

AI ChangeSet 发生：

```text
PartiallyApplied
```

结果：

- 产生高价值 Operation Event
- Dashboard 可统计
- Task Diagnostic 显示已应用与失败对象
- 可从 Operations Console 进入 Reconcile

---

### 场景 7：Dead Letter 积压

某消费者持续失败。

结果：

- oldest age / count 可见
- Alert 触发
- 可以查看失败原因
- 可以通过受控操作 Replay
- Replay 本身有 Audit

---

### 场景 8：敏感信息

代码抛异常时 Header 中包含：

```text
Authorization
```

结果：

```text
日志中 Token 被 Redact
```

不能明文进入日志平台。

---

### 场景 9：Reconnect Storm

大量客户端同时重连。

结果：

- Reconnect Rate 明显可见
- Alert / Dashboard 展示
- Backoff / Jitter 生效
- 可以确认系统是否重新稳定

---

### 场景 10：大 Workspace 异常

只有一个 Workspace 的 Import Worker 出现高失败。

结果：

- 系统可以识别影响范围
- 不误判为全站故障
- Workspace Diagnostic 可以定位具体任务

---

### 场景 11：发布回归

新版本上线后 Error Rate 上升。

结果：

```text
Metrics / Trace
```

可按：

```text
release version
```

比较。

运维能够判断问题从哪个版本开始。

---

### 场景 12：Break Glass

发生严重事故，需要紧急管理操作。

结果：

- 使用强认证
- 权限临时授予
- 自动过期
- 全量 Audit
- 产生高风险 Security Alert

---

### 场景 13：Reindex

Search Index 损坏。

运维：

```text
Trigger Reindex
```

结果：

- 通过正式 Admin Operation
- Task 可查询
- Progress 可见
- 有 Audit
- 不直接修改 Search 内部状态

---

### 场景 14：Orphan Asset 增长

Orphan Upload 数量异常升高。

结果：

- Metric 可见
- Cleanup Health 可见
- 告警可以在 Storage 爆满前触发

---

### 场景 15：日志量爆炸

某服务 BUG 导致高频错误日志。

结果：

- Log Rate 可监控
- Sampling / Rate Protection 生效
- 不因为日志系统把主业务打挂

---

### 场景 16：Observability Backend 故障

Trace / Log Backend 暂时不可用。

结果：

- 核心编辑功能继续
- Telemetry 使用有界 Buffer / Drop Policy
- 不能无限占用业务进程内存
- Security / Audit 按更高可靠性策略处理

---

## 130. 本地 AI 实现自由度

本设计不规定：

- 使用 OpenTelemetry 还是其他 Trace 标准
- 使用 Prometheus / VictoriaMetrics / 云 Metrics
- 使用 Loki / Elasticsearch / 云日志
- 使用 Grafana / Datadog / New Relic
- Alert Provider
- On-call 产品
- Dashboard 产品
- Incident 产品
- Audit Storage 技术
- Log Retention 具体天数
- Trace Sampling 比例
- SLO 具体数值
- Operations Console 前端技术
- Feature Flag 产品

本地 AI 可以根据项目规模、部署环境和成本选择。

但必须满足本设计的可观测性、安全、可恢复性和生产运维要求。

---

## 131. 架构硬约束

1. Logs、Metrics、Traces、Audit 必须职责分离。
2. 核心模块使用统一 requestId / traceId 上下文。
3. Resource / Task 问题必须能够通过 resourceId / taskId 快速定位。
4. 普通日志不得记录 Secret、完整 Token 和无必要正文。
5. 高基数字段不得无脑作为 Metrics Label。
6. 核心链必须监控 Availability、Latency、Errors、Saturation。
7. Persistence 必须暴露 Durable Lag。
8. Permission 必须暴露 Propagation Lag。
9. Search 必须暴露 Index Lag。
10. Queue / Event 必须监控 Consumer Lag 和 Oldest Pending Age。
11. Dead Letter / Failed Task 必须可见、可诊断、可重放。
12. 服务必须区分 Liveness 与 Readiness。
13. Critical Dependency 与 Degradable Dependency 必须分离。
14. Search / AI / Preview 等非核心依赖故障不能让整个系统判定不可用。
15. P1 / P2 Alert 必须关联 Dashboard 和 Runbook。
16. Audit 必须使用独立 Retention 与受控访问。
17. Operations Console 必须通过正式 Admin Command，不把直接改数据库作为正常运维方式。
18. 高风险 Break Glass 必须强认证、限时、Audit。
19. Feature Flag / Kill Switch / Dynamic Config 必须可追踪、可回滚。
20. 所有发布必须能关联 release / build version。
21. 长任务必须有 Task Diagnostic。
22. 系统必须支持 Resource / Workspace / Task 级诊断。
23. Telemetry 自身故障不能拖垮核心业务。
24. Observability 数据必须遵守隐私、最小化和 Retention。
25. 自动恢复只能用于可安全重试、幂等或无副作用操作。
26. 数据修复必须使用受控 Repair Plan / Admin Operation。
27. 重大 Incident 必须可形成 Timeline 和 Postmortem。
28. Capacity 必须提前监控和预警，不能等资源耗尽。
29. Client 与 Server Observability 必须可通过 requestId / traceId 关联。
30. Observability & Operations 遵守 Unified Module Communication Design。

---

## 132. 最终模型

```text
                    Production System
                           │
          ┌────────────────┼────────────────┐
          │                │                │
          ▼                ▼                ▼
        Logs             Metrics          Traces
          │                │                │
          └────────────┬───┴───────┬────────┘
                       │           │
                       ▼           ▼
                  Dashboards     Alerts
                       │           │
                       └─────┬─────┘
                             ▼
                         Operations
                             │
                 ┌───────────┼───────────┐
                 ▼           ▼           ▼
              Runbook     Diagnostics   Admin Actions
                                             │
                                             ▼
                                           Audit
```

关键诊断关系：

```text
requestId
→ 一次请求

traceId
→ 一条跨模块链路

resourceId
→ 一个协作对象

taskId
→ 一个长期异步操作

releaseId
→ 一次生产发布
```

系统必须保证：

> 出问题时，不需要猜；系统变慢时，不需要等用户投诉；安全边界失效时，不需要翻几十个服务日志；所有关键异常都应该能够被发现、关联、定位、恢复和复盘。
