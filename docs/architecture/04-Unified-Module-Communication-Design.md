# Unified Module Communication Design

## 1. 目标

本设计定义系统所有模块之间统一的通信规则。

目标不是强制所有模块使用同一种网络协议，而是让：

```text
Resource
Realtime Collaboration
Persistence
Permission
History
AI
Plugin
Search
Asset
Workspace / Project
Background Job
```

都遵守同一套交互语义、错误规则、身份规则、版本规则和可观测性要求。

统一的是：

```text
Communication Contract
```

不是：

```text
所有模块必须使用 WebSocket
所有模块必须使用 HTTP
所有模块必须使用 JSON
```

具体 Transport 可以根据场景选择。

---

## 2. 核心原则

系统内部交互统一划分为四种类型：

```text
Command
Query
Event
Stream
```

### Command

表示：

> 请求系统执行一个会改变状态的操作。

例如：

```text
修改权限
创建分享链接
发起 AI 修改
恢复历史版本
删除 Resource
```

---

### Query

表示：

> 请求读取当前状态或计算结果，不直接改变系统状态。

例如：

```text
查询 Resource
查询权限
查询历史版本
查询成员列表
查询 AI Task 状态
```

---

### Event

表示：

> 某件事情已经发生，通知其他模块。

例如：

```text
PermissionChanged
ResourcePurged
CheckpointCreated
HistoryRestored
MemberRemoved
```

Event 描述已发生的事实，不表达“请做某事”。

---

### Stream

表示：

> 持续传输实时状态或增量数据。

例如：

```text
Yjs Update
Awareness
实时任务输出
流式 AI Response
```

Stream 用于持续通信，不替代 Command / Query / Event。

---

## 3. 不同通信类型不得混用

禁止用 Event 表示 Command。

错误示例：

```text
Event: PleaseTrashResource
```

正确：

```text
Command: TrashResource
```

然后成功后产生：

```text
Event: ResourceTrashed
```

禁止用 Query 隐式修改状态。

禁止通过 Stream 承担所有系统控制逻辑。

禁止把 Command 当作“广播通知”。

---

## 4. Transport 与 Contract 分离

模块通信契约与具体 Transport 解耦。

允许：

```text
HTTP / RPC
WebSocket
Message Bus
Background Queue
Local In-Process Call
Binary Stream
```

具体选择由本地 AI 根据：

- 延迟要求
- 是否需要响应
- 是否跨服务
- 是否需要重试
- 是否持续流式
- 是否需要持久队列

决定。

但无论底层使用什么 Transport，都必须遵守本设计的语义规则。

---

## 5. Transport 推荐边界

### HTTP / RPC

适合：

```text
Command
Query
```

尤其是：

```text
需要立即响应
请求量可控
调用方明确
```

---

### Message Bus / Queue

适合：

```text
Event
Background Command
异步任务
```

尤其是：

```text
允许异步
需要重试
需要削峰
跨服务传播
```

---

### WebSocket / Realtime Transport

适合：

```text
Stream
Realtime Control
Subscription
```

---

### Yjs Binary Protocol

继续用于：

```text
Yjs Update
State Vector
Awareness
```

不得把 Yjs 二进制更新重新转换成业务 JSON Command。

---

## 6. 统一身份体系

系统模块之间不得为同一对象建立多套平行身份。

统一使用：

```text
workspaceId
projectId
resourceId
nodeId
userId
clientId
taskId
requestId
eventId
```

其中：

```text
ResourceRef
= resourceId

NodeRef
= resourceId + nodeId
```

文本内部位置继续使用：

```text
resourceId
+
nodeId
+
RelativePosition
```

不得用：

```text
DOM Position
数组下标
Yjs Internal ID
临时前端对象 ID
```

作为跨模块长期引用。

---

## 7. 统一调用上下文

需要跨模块追踪的请求，应携带统一上下文。

至少能够表达：

```text
requestId
traceId
actor
resource scope
client context
idempotencyKey（仅需要安全重试的 Command）
```

其中：

### requestId

标识一次具体请求 / attempt。

用于：

- 日志关联
- 错误定位
- 请求响应关联

网络重试产生新的请求实例时，应生成新的 `requestId`。

### idempotencyKey

标识一个可安全重试的逻辑 Command。

同一个业务动作因为网络超时、客户端重试或队列重放再次提交时：

```text
idempotencyKey 保持稳定
requestId 可以变化
```

Query、纯 Stream 数据和不需要幂等语义的 Control Message 不要求携带 `idempotencyKey`。

### traceId

用于跨多个模块追踪同一条业务链。

例如：

```text
User
↓
AI Task
↓
Permission
↓
Resource
↓
Persistence
↓
History
```

应能通过同一 trace 关联。

### actor

表示当前操作主体。

可能是：

```text
User
AI Task
Plugin
System Job
Migration
```

actor 不能替代权限判断。

---

## 8. 权限上下文

模块之间不能通过：

```text
role = Edit
```

就默认信任调用方已经授权。

真正产生状态变化的模块仍必须基于统一 Permission System 验证当前操作能力。

尤其包括：

```text
Realtime Update
AI Write
Plugin Write
History Restore
Resource Trash / Purge
Share Change
Permission Change
```

内部模块调用不能因为“来自后端服务”就自动获得全部权限。

---

## 9. Command 设计要求

所有 Command 必须：

- 表达清楚的业务动作
- 明确目标对象
- 明确当前 Actor
- 可判断成功 / 失败
- 支持幂等或安全重试
- 不依赖调用方重复猜测结果

例如：

```text
ChangeMemberRole
RestoreVersion
CreateShareLink
StartAITask
TrashResource
```

Command 不应该命名成：

```text
DoSomething
UpdateData
Process
Handle
Action
```

这种无法表达业务语义的名称。

---

## 10. Command 幂等

所有可能因网络重试、队列重放、客户端双击而重复到达的 Command 必须具备幂等策略。

重点包括：

```text
InviteMember
AcceptInvite
ChangeMemberRole
TrashResource
PurgeResource
RestoreVersion
CreateShareLink
RevokeShareLink
StartAITask
ApplyChangeSet
```

重复执行不能产生：

```text
双重成员
双重 Owner
重复历史恢复
重复 AI 修改
重复删除
重复收费任务
```

`idempotencyKey` 是跨客户端与服务端 Contract 的统一字段；事务、去重存储和重复结果返回方式由本地 AI 选择。

---

## 11. Query 设计要求

Query 必须：

- 不产生业务副作用
- 支持缓存
- 可以被重复调用
- 明确数据新鲜度
- 明确权限边界

如果一个 Query 会改变状态，就应该重新定义为 Command。

---

## 12. Event 设计要求

Event 表示已经发生的事实。

Event 命名使用过去式或完成语义，例如：

```text
ResourceCreated
ResourceTrashed
ResourcePurged
PermissionChanged
MemberRemoved
CheckpointCreated
HistoryRestored
AITaskCompleted
PluginInstalled
```

Event 不要求所有消费者都存在。

生产者不能依赖“所有消费者都处理成功”以后才认为自己的业务操作成功。

### 12.1 Canonical Contract Naming

跨模块稳定名称必须服从对应 Domain 的 Canonical Owner。

当前统一词汇至少包括：

```text
TrashResource / ResourceTrashed
PurgeResource / ResourcePurged
RestoreResource / ResourceRestored
ArchiveProject / ProjectArchived
UnarchiveProject / ProjectUnarchived
RestoreVersion / HistoryRestored
ApplyChangeSet / ChangeSetApplied
InviteMember
ChangeMemberRole / PermissionChanged
AITaskCompleted
```

本文件中的示例不能反向覆盖 Domain Owner 已确定的正式名称。若示例与 Canonical Owner 冲突，以 Canonical Owner 为准，并应修正文档而不是让实现层兼容两套名字。

---

## 13. Event 必须可版本化

所有跨模块 Event 必须支持 Schema Version。

例如：

```text
PermissionChanged v1
PermissionChanged v2
```

新增字段优先保持向后兼容。

破坏性修改必须创建新版本。

不能在已有消费者仍运行时直接改变 Event 含义。

---

## 14. Event 去重

Event Bus 可能产生重复投递。

消费者必须能够安全处理重复 Event。

默认设计原则：

> Event 至少一次投递可以接受，但消费者必须幂等。

不要为了追求理论上的 Exactly Once，把系统设计得异常复杂。

---

## 15. Event 顺序

不假设所有系统 Event 全局有序。

只在真正需要时保证：

```text
同一个 Resource
同一个 Task
同一个 Permission Subject
```

内部的局部顺序。

例如：

```text
PermissionChanged
↓
MemberRemoved
```

如果业务确实依赖顺序，应使用该对象自己的序列或状态版本。

不要设计全局事件总序列。

---

## 16. Event 最终一致

通过 Event 同步的派生系统允许短暂最终一致。

例如：

```text
Search Index
Analytics
Audit Projection
AI Index
Notification
```

可以稍后更新。

但以下能力不能依赖长期最终一致：

```text
权限校验
实时写入授权
Resource 是否已删除
Owner 当前状态
```

安全和核心状态必须使用权威来源。

---

## 17. Stream 设计要求

Stream 用于持续数据流。

包括：

```text
Yjs Sync
Awareness
Realtime Task Output
AI Streaming
```

Stream 必须具备：

- 生命周期
- 断线处理
- Backpressure
- 取消
- 超时
- 重连策略
- 错误结束状态

不能假设 Stream 永远稳定存在。

---

## 18. Realtime Stream 特殊规则

Yjs Stream 继续使用已有：

```text
Realtime Collaboration Protocol Design
```

定义。

本协议只规定：

> Realtime Collaboration 是统一模块通信体系中的 Stream 类通信。

Yjs Update、State Vector、Awareness 不需要重新包装成普通业务 Event。

---

## 19. Async Task 模型

所有长时间后台工作统一使用：

```text
Async Task
```

本文件只定义它属于统一模块通信中的正式业务模式。

Task / Attempt / Lease / Retry / Cancel / Progress / Priority / Dead Letter / Worker Recovery 的 Canonical Owner 是：

```text
25-Async-Task-Execution-Design.md
```

Domain 模块只能增加自己的：

```text
taskType
domain stage
domain result
```

不得重新定义通用 Task Runtime。

客户端对 Task 的通用原则仍然是：

```text
Command 创建 / 控制
Query 恢复当前状态
Event 表示状态事实
Stream 提供实时进度
```

Task 生命周期不能依赖某个 WebSocket 持续在线。

---

## 23. 错误模型

系统必须采用统一错误语义。

错误至少区分：

```text
Validation
Authentication
Permission
NotFound
Conflict
RateLimit
Timeout
DependencyFailure
Unavailable
Internal
```

这些是顶层 Error Category。具体 Domain 使用稳定 `errorCode` 细分，前端不得依赖 message 文本判断错误类型。

模块不得各自返回完全不同的错误风格。

---

## 24. Error Scope

错误应控制在最小影响范围。

例如：

```text
一个 Resource 操作失败
```

不能默认造成：

```text
整个 Project 请求失败
整个 WebSocket 关闭
整个 Worker 崩溃
```

系统级错误只有在真正无法继续运行时才扩大影响范围。

---

## 25. 错误不得泄露内部实现

客户端可见错误应包含：

```text
errorCode
human message
requestId
必要的恢复提示
```

不得直接暴露：

```text
数据库连接字符串
服务器路径
内部堆栈
Token
Secret
内部 SQL
```

详细错误进入内部日志和 Trace。

---

## 26. Timeout

所有跨服务 Command / Query 必须有明确 Timeout。

禁止：

```text
无限等待
```

不同类型操作可以拥有不同 Timeout。

具体时间由实现和压测确定。

超时后不能默认假设操作一定失败。

对于可能已经成功的 Command，应结合：

```text
requestId
idempotency
status query
```

确认最终状态。

---

## 27. Retry

只对安全操作进行自动 Retry。

适合自动重试：

```text
幂等 Query
幂等 Command
Event Consumption
Transient Dependency Failure
```

不适合未经保护直接重试：

```text
非幂等支付
重复 AI Apply
重复 Restore
重复 Owner Transfer
```

必须先具备幂等保护。

---

## 28. Retry Backoff

重试必须使用受控 Backoff。

禁止所有服务在依赖恢复后同时立即打满请求。

需要：

```text
exponential backoff
jitter
retry limit
```

具体参数由本地 AI 根据基础设施确定。

---

## 29. Circuit Breaker / Degraded State

关键依赖持续失败时，系统应避免无限重试。

例如：

```text
Search 挂了
```

不应该拖垮：

```text
Realtime Editing
Permission
Persistence
```

模块必须支持可控降级。

核心编辑路径与非核心派生能力隔离。

---

## 30. Backpressure

所有可能高吞吐的通信都必须考虑 Backpressure。

包括：

```text
Event Bus
Realtime Stream
AI Stream
Import
Export
Indexing
Persistence Journal
```

不能使用无限内存队列。

系统必须具备：

- 队列上限
- 速率限制
- 合并
- 延迟处理
- 丢弃允许丢弃的数据
- 拒绝超载请求

等至少一种保护机制。

---

## 31. 可丢弃与不可丢弃数据

系统必须区分：

### 不可静默丢弃

```text
Resource State Change
Permission Change
Yjs Update
History Restore Result
Critical Audit Event
```

### 可以合并或丢弃旧状态

```text
Cursor
Selection
Presence
Progress Tick
Telemetry Sample
```

不能把所有消息一视同仁。

---

## 32. 一致性边界

不同模块根据业务价值使用不同一致性策略。

### 强一致 / 权威读取

用于：

```text
Permission
Owner
Resource Lifecycle
Critical Write
```

### 最终一致

用于：

```text
Search
Analytics
Notification
AI Index
Derived Preview
```

### CRDT 收敛一致

用于：

```text
Realtime Resource Content
```

不要强迫所有模块使用同一种一致性模型。

---

## 33. Resource 是跨模块主路由键

涉及某个具体协作对象的模块通信，优先以：

```text
resourceId
```

作为主路由和关联键。

例如：

```text
PermissionChanged(resourceId)
CheckpointCreated(resourceId)
HistoryRestored(resourceId)
AITask(resourceId)
SearchIndex(resourceId)
```

Node 级操作再增加：

```text
nodeId
```

避免再次产生：

```text
documentId
fileId
roomId
collaborationId
historyResourceId
```

等平行身份。

---

## 34. 跨 Resource 操作

一次业务操作可能同时影响多个 Resource。

例如：

```text
AI 同时修改 3 个代码文件
批量移动多个 Resource
批量权限变更
Project Import
```

这类操作不能假设由单个 Resource Transaction 自动完成。

统一采用：

```text
Operation / ChangeSet / Task
```

管理整体状态。

需要能够表达：

- 涉及哪些 Resource
- 哪些子操作成功
- 哪些失败
- 当前整体状态
- 是否可以重试
- 是否需要补偿

具体事务实现由对应业务模块设计。

---

## 35. 跨模块事务

默认不设计分布式数据库事务覆盖所有模块。

优先使用：

```text
Local Transaction
+
Event
+
Idempotent Consumer
+
Compensation
```

构建可靠业务流程。

只有极少数真正需要原子性的核心状态才在同一权威存储中完成。

不要为了追求“所有东西同时成功”引入大范围全局锁。

---

## 36. Outbox / Reliable Event Publish

当一个模块完成关键状态写入并需要发送 Event 时，必须避免：

```text
数据库写成功
+
Event 发送失败
```

导致其他系统永远不知道状态变化。

生产级实现应采用：

```text
Transactional Outbox
```

或其他等价可靠发布机制。

具体技术由本地 AI 根据数据库和消息基础设施选择。

---

## 37. Inbox / Consumer Dedup

重要 Event 消费者应支持：

```text
Inbox / Dedup
```

或等价机制。

目的：

- 防止重复 Event 导致重复副作用
- 支持消费者安全重启
- 支持消息重新投递

---

## 38. Schema Registry

跨模块稳定消息必须有统一 Schema 管理。

至少包括：

```text
Command Schema
Query Schema
Event Schema
Task Schema
Error Schema
```

不要求必须部署独立 Schema Registry 服务。

但项目中必须有明确的：

```text
统一定义来源
版本规则
兼容规则
```

禁止各模块复制粘贴相似类型后独立演化。

---

## 39. Contract 共享

TypeScript、Python、Rust 等模块之间需要共享相同通信语义。

可以使用：

```text
OpenAPI
JSON Schema
Protobuf
MessagePack Schema
自定义 IDL
Code Generation
```

或其他成熟方案。

具体工具由本地 AI根据项目技术栈决定。

要求是：

> Contract 必须有一个权威来源，不能靠人工同时维护三份不同定义。

---

## 40. 二进制数据

对于：

```text
Yjs Update
Asset Chunk
Large Binary Payload
```

不要为了“统一 JSON”而转换成 Base64。

应保留二进制通道。

业务元数据和二进制 Payload 可以分离。

---

## 41. 大 Payload

大型数据不应直接塞入普通 Command / Event。

例如：

```text
视频
图片
完整导出文件
大型 AI Context
完整数据库 Dump
```

应通过：

```text
Asset / Object Storage / File Transfer
```

处理。

模块消息只传：

```text
assetId
objectRef
taskId
```

等引用。

---

## 42. Audit Context

高风险 Command 应携带或生成可追踪的审计上下文。

包括：

```text
actor
target
action
requestId
result
timestamp
```

安全审计不是所有 Event 的简单复制。

审计系统拥有自己的长期数据模型。

---

## 43. 可观测性

所有模块通信必须可追踪。

至少监控：

```text
request latency
command success / failure
query latency
event publish latency
event consumer lag
retry count
timeout count
dead letter count
stream disconnect
queue depth
task duration
task failure
permission denied
dependency failure
```

跨模块 Trace 必须能够通过：

```text
traceId
requestId
resourceId
taskId
```

定位一次完整业务链。

---

## 44. Dead Letter

无法在合理重试后成功处理的重要 Event / Background Command：

```text
不能无限重试
不能直接静默删除
```

应进入：

```text
Dead Letter / Failed Task
```

并具备：

- 可观察
- 可诊断
- 可重放
- 可人工处理

能力。

---

## 45. 服务启动与兼容性

服务启动时应验证：

- 必要 Contract Version 是否兼容
- 必要依赖是否可用
- 当前 Event Consumer 是否认识目标版本
- 不兼容时是否需要拒绝启动或降级

不能让版本不兼容问题运行到用户操作时才随机爆炸。

---

## 46. 多实例部署

任何模块都不能假设：

```text
系统里只有一个实例
```

生产设计必须支持：

```text
Service A1
Service A2
Service A3
```

同时运行。

需要避免：

- 仅依赖单机内存做全局状态
- 单实例事件通知
- 单机锁作为全局锁
- 本地缓存永久有效

具体分布式方案由本地 AI 根据基础设施实现。

---

## 47. 模块隔离

非核心模块故障不能拖垮实时编辑主链。

例如：

```text
Analytics Down
Search Down
Notification Down
AI Down
```

不应该自动导致：

```text
Resource 无法编辑
Yjs 无法同步
Permission 无法校验
Persistence 无法落盘
```

核心依赖和可降级依赖必须区分。

---

## 48. 推荐模块通信图

```text
                         ┌────────────────────┐
                         │ Unified Contracts  │
                         └─────────┬──────────┘
                                   │
             ┌─────────────────────┼─────────────────────┐
             │                     │                     │
             ▼                     ▼                     ▼
          Command                Query                  Event
             │                     │                     │
     ┌───────┼───────┐     ┌──────┼──────┐     ┌────────┼────────┐
     ▼       ▼       ▼     ▼      ▼      ▼     ▼        ▼        ▼
 Resource  AI     Permission History Search Permission Persistence Audit
             │
             │
             ▼
            Task

                                   │
                                   ▼
                                 Stream
                                   │
                         ┌─────────┼─────────┐
                         ▼                   ▼
                    Realtime Yjs         AI Output
```

这张图表达的是通信语义。

并不要求所有箭头都使用同一种网络协议。

---

## 49. 与 Realtime Collaboration Protocol 的关系

`Realtime Collaboration Protocol Design` 继续负责：

```text
Connection
Subscription
Resource Session
Yjs Sync
Awareness
Backpressure
Reconnect
Realtime Transport
```

本设计负责更高一层：

```text
所有系统模块之间如何统一表达 Command / Query / Event / Stream
```

二者关系：

```text
Unified Module Communication
        │
        └── Stream
              │
              └── Realtime Collaboration Protocol
```

因此：

> Realtime Collaboration Protocol 是统一通信体系的实时子协议，不是整个系统所有模块的总通信协议。

---

## 50. 与 Persistence 的关系

Persistence 通过统一通信体系提供：

```text
Query
读取恢复状态

Event
CheckpointCreated
PersistenceDegraded

Background Task
Compaction
Checkpoint
```

但 Yjs Journal 热路径仍按 Persistence Design 自己的高性能边界实现。

统一通信体系不强迫 Persistence 把每条 Yjs Update 转成业务 Event。

---

## 51. 与 Permission 的关系

Permission 提供统一 Query / Decision 能力。

同时发布：

```text
PermissionChanged
MemberRemoved
ShareRevoked
```

等 Event。

Realtime、AI、Plugin 等模块消费这些变化，及时失效自己的授权上下文。

---

## 52. 与 History 的关系

History 主要使用：

```text
Query
查询版本

Command
恢复版本

Event
HistoryRestored
VersionCreated
```

History Restore 如果是耗时操作，可以进入统一 Async Task 模型。

---

## 53. 与 AI 的关系

AI 主要使用：

```text
Command
启动任务

Query
读取 Context

Task
管理长任务

Stream
输出生成过程

Command
最终应用修改

Event
任务完成 / 失败
```

AI 不直接绕过 Resource、Permission 和统一通信规则。

---

## 54. 与 Plugin 的关系

Plugin 调用同样进入统一 Contract。

Plugin 不允许：

```text
自己直接操作数据库
自己绕过 Permission
自己定义另一套 Resource ID
```

所有跨模块调用必须走正式能力边界。

---

## 55. 第一版必须具备

第一版上线前至少具备：

```text
Command / Query / Event / Stream 四类语义
统一 Resource / Node Identity
统一 Error Model
统一 Request / Trace Context
Command 幂等
Event Version
Event 去重
Timeout / Retry
Async Task
Backpressure
权限上下文
统一 Contract Source
跨语言 Schema
基础可观测性
Reliable Event Publish
Failed Task / Dead Letter
```

这不是 Demo 可选项，而是生产级模块通信的基础。

---

## 56. 第一版不需要过度设计

第一版不需要：

```text
全局分布式事务
全局严格事件顺序
Exactly Once Event Delivery
自研 RPC Framework
自研 Message Broker
自研 IDL
所有模块强制微服务化
```

优先使用成熟基础设施。

统一的是通信契约，不是基础设施品牌。

---

## 57. 核心验收场景

### 场景 1：权限变化传播

```text
Permission
↓
PermissionChanged Event
↓
Realtime / AI / Plugin
↓
旧授权失效
```

结果：

- 不需要模块轮询数据库
- 重复 Event 不产生异常副作用
- 某个消费者暂时离线后可以恢复消费

---

### 场景 2：AI 长任务

```text
Start AI Command
↓
Task Created
↓
AI Stream 输出
↓
Apply Change Command
↓
Resource 修改
↓
Task Finished Event
```

结果：

- 页面关闭后 Task 仍存在
- 重连后可以继续查询 Task
- 最终写入重新鉴权
- 重复请求不会重复 Apply

---

### 场景 3：History Restore

```text
RestoreVersion Command
↓
Async Task
↓
Permission Check
↓
Resource Restore
↓
Persistence
↓
HistoryRestored Event
```

结果：

- 请求超时不代表重复恢复
- requestId / taskId 可以查询最终状态
- 其他模块能收到 Restore 事实

---

### 场景 4：Search 故障

Search 服务不可用。

结果：

```text
Resource Editing
Realtime
Permission
Persistence
```

继续工作。

Search 恢复后可以通过 Event / Rebuild 补齐。

---

### 场景 5：Event 重复

同一个：

```text
ResourcePurged
```

Event 被投递两次。

消费者不能重复执行破坏性操作。

---

### 场景 6：消费者宕机

Audit Consumer 暂时宕机。

生产者继续正常运行。

Consumer 恢复以后能够继续处理未消费事件。

---

### 场景 7：事件版本升级

新版本服务开始发送：

```text
PermissionChanged v2
```

旧消费者不能因为多一个兼容字段直接崩溃。

破坏性协议变化必须显式升级版本。

---

### 场景 8：多服务实例

同一模块运行多个实例。

结果：

- 不依赖单机内存才能正确处理请求
- Event 不会因为连接到不同实例而永久丢失
- Idempotency 在多实例下仍然有效

---

### 场景 9：大 Payload

用户上传大型文件。

模块通信传递：

```text
assetId
```

而不是把文件二进制塞进普通 Event Bus。

---

### 场景 10：超时后状态不确定

调用方发送一个写 Command 后超时。

结果：

```text
不能直接再次无保护执行
```

应通过：

```text
requestId / taskId
```

确认状态或安全重试。

---

## 58. 架构硬约束

1. 系统模块通信统一采用 `Command / Query / Event / Stream` 四类语义。
2. 统一通信契约与具体 Transport 分离。
3. 不强制所有模块使用同一种协议、编码或网络连接。
4. Yjs Sync / Awareness 保留二进制实时协议，不转换成普通业务 Command。
5. Resource 是跨模块协作对象的主路由边界，统一使用 `resourceId`。
6. Node 跨模块引用统一使用 `NodeRef`。
7. 所有关键 Command 必须支持幂等或安全重试。
8. Event 表示已经发生的事实，不承担 Command 语义。
9. Event 必须支持版本、重复投递和消费者幂等。
10. 不建立全局事件严格顺序，只在必要对象范围内保证局部顺序。
11. 长任务统一使用可持久恢复的 Async Task 模型。
12. 长任务不能依赖客户端连接持续存在。
13. 所有跨服务调用必须有 Timeout。
14. Retry 必须建立在幂等或安全重试基础上。
15. 高吞吐通道必须具备 Backpressure。
16. 大型 Payload 通过 Asset / Object Storage 传输，模块消息只传引用。
17. 核心状态与派生状态使用不同一致性等级。
18. 关键状态写入与 Event 发布必须使用可靠发布机制。
19. Event Consumer 必须支持重复消费保护。
20. 无法处理的重要消息不能静默丢弃，应进入 Failed Task / Dead Letter。
21. Contract 必须有唯一权威定义来源，并支持跨 TypeScript / Python / Rust 使用。
22. 跨模块 Trace 必须能关联 requestId、traceId、resourceId、taskId。
23. 非核心模块故障不得默认拖垮 Realtime / Permission / Persistence 核心路径。
24. 第一版不自研 RPC、Message Broker、IDL 或全局分布式事务。
25. `Realtime Collaboration Protocol Design` 是本统一通信体系中的 Stream 子协议。

---

## 59. 最终定位

本设计是系统所有模块共同遵守的通信总规范。

它解决：

```text
模块之间怎么说话
消息属于什么语义
怎么追踪
怎么重试
怎么失败
怎么版本升级
怎么处理长任务
怎么防止重复副作用
怎么保持跨语言一致
```

它不解决：

```text
每个模块自己的业务逻辑
Yjs 内部 CRDT 算法
具体数据库结构
具体消息中间件选型
具体 RPC 框架
```

系统后续新增模块时，应首先接入这套统一 Communication Contract，而不是自行创建新的通信风格。
