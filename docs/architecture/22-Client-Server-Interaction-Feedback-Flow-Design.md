# Client-Server Interaction & Feedback Flow Design

## 1. 目标

本设计定义官方客户端与后端之间一次完整业务交互如何流动，以及每种交互在前端如何获得明确、可恢复、可诊断的反馈状态。

本模块解决：

> 用户点击、输入或触发一个动作以后，前端如何表达 Pending，后端什么时候算 Accepted，什么时候算真正完成，异步任务如何反馈 Progress，Realtime 如何区分 Local / Synced / Durable，失败、冲突、权限变化、Session Replacement、断网和重连时前端应该收到什么系统状态，以及多个客户端如何最终看到一致结果。

本设计不决定 UI 长什么样。

它只定义：

```text
信息从哪里来
状态是什么意思
什么时候改变
哪个模块负责
失败后如何恢复
```

---

## 2. 核心原则

所有用户可见操作都必须拥有明确状态机。

禁止：

```text
点击按钮
↓
前端自己假设成功
```

统一原则：

```text
Intent
↓
Pending
↓
Backend Acknowledge
↓
Confirmed / Rejected
↓
如果是异步工作
Processing
↓
Succeeded / Failed / Cancelled
```

Realtime 编辑是特殊路径：

```text
Local
↓
Syncing
↓
Synced
↓
Durable
```

---

## 3. 状态语义必须来自系统

UI 可以自由设计：

```text
图标
文字
动画
颜色
位置
```

但以下语义不能由 UI 自己发明：

```text
Pending
Accepted
Processing
Succeeded
Failed
Conflict
ReadOnly
Offline
Reconnecting
Synced
Durable
SessionReplaced
```

这些必须来自统一 Contract。

---

## 4. 交互类型

客户端与后端统一分为：

```text
Query
Command
Async Task
Realtime Stream
Offline / Reconnect
System Control Event
```

每类拥有独立反馈模型。

---

# Part A: Query Flow

## 5. Query 状态机

Query：

```text
Idle
↓
Loading
↓
Ready
```

也可能：

```text
Loading
↓
Empty
```

或：

```text
Loading
↓
Error
```

---

## 6. Query Flow

```text
UI Intent
↓
Feature Module
↓
Client SDK
↓
Query
↓
Gateway
↓
Backend Module
↓
Authoritative Read
↓
Response
↓
Query Cache
↓
Feature State
```

---

## 7. Query 不产生业务副作用

例如：

```text
GetProjectTree
ListNotifications
GetResourceMetadata
SearchResources
```

不得改变：

```text
Resource
Permission
Task
History
```

---

## 8. Query Cache 命中

前端可：

```text
先显示缓存
↓
后台 Revalidate
```

但 UI 必须能区分：

```text
Cached Data
Refreshing
Fresh Data
```

不要求视觉暴露，但内部状态要明确。

---

## 9. Query 失败

Query 失败不能修改上次已成功数据为：

```text
空
```

默认应保留：

```text
last known good state
```

并附加：

```text
refresh error
```

除非当前数据已明确无效。

---

## 10. Query 与 Permission

Query 返回：

```text
PermissionDenied
```

表示：

```text
当前 Actor 无权读取
```

不能被前端当成：

```text
Empty
```

---

# Part B: Synchronous Command Flow

## 11. Command 状态机

普通同步 Command：

```text
Idle
↓
Pending
↓
Succeeded
```

或：

```text
Pending
↓
Rejected
```

---

## 12. Command Flow

```text
User Intent
↓
Feature Module
↓
Client SDK
↓
Command + requestId
+ idempotencyKey（仅需要安全重试的 Mutating Command）
↓
Gateway
↓
Auth / Permission
↓
Domain Validation
↓
PostgreSQL Transaction
↓
Commit
↓
Response
↓
Frontend Confirmed
```

如果有 Outbox：

```text
Commit
↓
Outbox
↓
Event
↓
Other Clients
```

---

## 13. HTTP 200 的语义

对于同步 Command：

```text
HTTP Success
```

仅表示：

```text
该 Command 已按 Contract 成功处理
```

不能把：

```text
HTTP Transport 成功
```

与：

```text
业务最终成功
```

混淆。

---

## 14. Optimistic UI

部分 Command 可以：

```text
Pending UI
↓
先局部乐观展示
```

例如：

```text
Rename Resource
Mark Notification Read
Create Comment
```

但必须支持：

```text
Rollback
Server Rejection
Conflict
```

---

## 15. 高风险 Command

以下不应只靠乐观结果：

```text
Owner Transfer
Permanent Delete
Permission Change
Account Delete
History Restore
AI Multi-resource Apply
```

它们必须等待服务端正式确认。

---

# Part C: Async Task Flow

## 16. Async Task 状态机

Async Task 的 Canonical State 由：

```text
25-Async-Task-Execution-Design.md
```

定义：

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

本文件只定义这些状态如何反馈给客户端。

Domain Stage：

```text
AI ReadyForReview
Export Packaging
Import Validating
```

不得被前端误认为另一套 Generic Task State。

---

## 17. Async Command Response

例如：

```text
StartExport
StartImport
StartAITask
RestoreLargeHistory
```

客户端收到：

```text
taskId
status
```

这只代表：

```text
任务已创建 / 接受
```

不代表最终完成。

---

## 18. Async Flow

```text
Command
↓
Task Created
↓
HTTP Response(taskId)
↓
Frontend Accepted
↓
Task Stream
↓
Progress
↓
Succeeded / Failed
↓
Query Final Result
```

---

## 19. Stream 不是唯一完成信号

如果 Task Stream 丢失：

```text
GetTask(taskId)
```

必须能恢复最终状态。

因此：

```text
Stream = 实时反馈
Query = 权威恢复
```

---

## 20. Task Progress

Progress 必须表达：

```text
stage
state
optional percentage
optional message code
```

不要求所有任务都有精确百分比。

禁止伪造：

```text
47%
63%
82%
```

但后端其实无法测量。

---

## 21. Task Result

最终成功：

```text
Succeeded
```

后客户端应：

```text
Query Result
```

或读取：

```text
result reference
```

不能仅依赖最后一条 Stream 文本。

---

# Part D: Realtime Editing Flow

## 22. Realtime 状态

正文协作必须区分：

```text
Local
Syncing
Synced
Durable
```

---

## 23. Local

```text
Local
```

表示：

> 用户修改已经进入本地 Y.Doc，并立即反映到本地 UI。

不代表服务器已收到。

---

## 24. Syncing

```text
Syncing
```

表示：

> 当前存在尚未完成网络同步的本地状态。

---

## 25. Synced

```text
Synced
```

表示：

> 相关 CRDT 状态已经与当前服务器协作 Session 完成同步。

不等于：

```text
Durable
```

---

## 26. Durable

```text
Durable
```

表示：

> 服务器已经确认相关状态进入 Durable Journal 或等价可靠持久化边界。

---

## 27. 禁止混淆

不能显示：

```text
Saved
```

但实际只有：

```text
Local
```

也不能把：

```text
WebSocket send success
```

当作：

```text
Durable
```

---

## 28. Realtime Flow

```text
User Input
↓
Editor Transaction
↓
Local Y.Doc
↓
UI Immediate
↓
Realtime Client Queue
↓
Realtime Gateway
↓
Resource Session
↓
Y.Doc Merge
↓
acceptedWatermark / equivalent receipt
↓
Durable Journal
↓
durableWatermark / equivalent receipt
```

这里的 receipt 是批量状态边界，不是每个字符一个业务 ACK。

客户端状态只能这样推进：

```text
Local
→ 服务端 acceptance boundary 覆盖本地修改 → Synced
→ persistence durable boundary 覆盖该修改 → Durable
```

`WebSocket.send()` 成功、收到任意远端消息或连接仍然在线，都不能单独作为 `Synced / Durable` 的依据。

---

## 29. Remote Update

其他用户修改：

```text
Remote Yjs Update
↓
Realtime Stream
↓
Local Y.Doc Merge
↓
Editor Render
```

不经过：

```text
普通 Redux / Query Cache
```

---

# Part E: Offline Flow

## 30. Offline 状态机

```text
Online
↓
Degraded
↓
Offline
↓
Reconnecting
↓
Syncing
↓
Synced
```

---

## 31. Offline Edit

已缓存 Resource：

```text
Offline
↓
Local Edit
↓
Local Y.Doc
↓
Offline Store
```

用户可以继续工作。

---

## 32. Reconnect

```text
Network Returns
↓
Session Validate
↓
Permission Re-check
↓
Resource Subscribe
↓
State Vector Exchange
↓
CRDT Diff
↓
Merge
↓
Synced
↓
Durable
```

---

## 33. Offline Permission Change

离线期间：

```text
Edit → Read
```

恢复网络后：

```text
Permission Re-check
↓
Reject Remote Write
↓
Frontend ReadOnly
```

本地修改：

```text
保留
```

不能静默清除。

---

## 34. Offline Resource Deleted

离线期间 Resource 被 Trash / Delete：

```text
Reconnect
↓
Lifecycle Check
↓
TargetUnavailable / ReadOnly
```

本地内容进入：

```text
Recovery Path
```

不能自动创建新 Resource 覆盖。

---

# Part F: Permission Feedback Flow

## 35. PermissionChanged

```text
Backend Permission Change
↓
PermissionChanged Event
↓
Client Capability State
↓
Dependent Features Update
```

影响：

```text
Editor
Comment
AI
History
Asset
Share
Toolbar Capability
```

---

## 36. Edit → Read

用户正在编辑：

```text
Edit
↓
PermissionChanged
↓
ReadOnly
↓
Realtime Write Stop
```

如果存在：

```text
Local Unsynced Changes
```

必须进入保护状态。

---

## 37. Permission Event 丢失

即使没收到 Event：

```text
下一次 Command / Update
```

服务器仍必须重新鉴权。

客户端 Event 只是快速反馈。

---

# Part G: Session Feedback Flow

## 38. Session State

客户端统一：

```text
Unknown
Validating
Authenticated
Expired
Replaced
LoggedOut
Disabled
```

---

## 39. Session Replaced

```text
New Device Login
↓
Old Session Revoked
↓
SessionReplaced Event
↓
All Tabs
↓
Stop Authenticated Commands
↓
Close Realtime
↓
Protect Unsynced Local Content
↓
Require Login
```

---

## 40. Session Expired

普通过期：

```text
SessionExpired
```

与：

```text
SessionReplaced
```

必须区分。

用户看到的 UI 可以不同。

---

# Part H: Conflict Flow

## 41. Conflict

部分业务操作可能返回：

```text
Conflict
```

例如：

```text
AI ChangeSet Base Changed
Rename Conflict
Restore Conflict
Import Replace Conflict
```

---

## 42. Conflict 状态机

```text
Pending
↓
Conflict
↓
Reload / Rebase / Review
↓
Retry / Cancel
```

不能自动：

```text
last writer wins
```

覆盖当前数据。

---

## 43. Conflict Payload

应返回：

```text
errorCode
current reference / version
conflict scope
recommended next action
```

但不返回内部数据库细节。

---

# Part I: Partial Failure

## 44. PartialSucceeded

跨 Resource / 多步骤操作可能：

```text
PartialSucceeded
```

例如：

```text
AI Multi-resource Apply
Import Project
Bulk Operation
```

---

## 45. Partial Result

客户端必须能够获得：

```text
succeeded items
failed items
retryable items
operationId
```

不能把 Partial Failure 显示成：

```text
全部失败
```

或：

```text
全部成功
```

---

# Part J: Event Feedback

## 46. Command 与 Event

同一操作可能：

```text
Command Response
+
Event
```

例如：

```text
RenameResource
↓
Response Success
↓
ResourceRenamed Event
```

当前发起客户端：

```text
Response
```

用于完成 Pending。

其他客户端：

```text
Event
```

用于更新状态。

---

## 47. Event 去重

当前客户端可能既：

```text
收到 Command Result
```

又：

```text
收到对应 Event
```

前端必须：

```text
idempotent update
```

不能重复插入数据。

---

# Part K: Navigation Feedback

## 48. Stable Target

Notification / Search / Comment / History：

```text
TargetRef
↓
Navigation Resolver
↓
Route
↓
Feature Runtime
```

---

## 49. TargetUnavailable

目标可能：

```text
Deleted
NoPermission
Expired
Detached
```

客户端必须获得明确：

```text
TargetUnavailable Reason
```

而不是无响应。

---

# Part L: Error Feedback

## 50. Error Envelope

所有客户端可见错误统一包含：

```text
errorCode
category
requestId
retryable
optional field errors
optional target state
```

---

## 51. Error Category

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

---

## 52. Frontend Mapping

前端将：

```text
errorCode
```

映射成具体用户反馈。

后端不依赖中文字符串作为逻辑。

---

## 53. Internal Error

未知异常：

```text
Internal
+
requestId
```

用户不看到：

```text
stack trace
SQL
provider secret
internal hostname
```

---

# Part M: Multi-tab Feedback

## 54. 多 Tab

同设备多个 Tab：

```text
共享 Session
```

但：

```text
Runtime 独立
```

---

## 55. 本地广播

可以通过：

```text
BroadcastChannel
```

快速传播：

```text
Logout
SessionReplaced
Notification Badge
Cache Invalidation
```

但它不是权威来源。

---

## 56. Cross-tab Recovery

如果本地广播丢失：

```text
Session Validate
Query Refresh
Realtime Reconnect
```

仍必须最终恢复正确状态。

---

# Part N: Frontend Feedback State Model

## 57. 统一动作状态

Feature Module 可以复用：

```text
Idle
Pending
Accepted
Processing
Succeeded
Failed
Conflict
Cancelled
```

---

## 58. 统一连接状态

```text
Online
Degraded
Offline
Reconnecting
```

---

## 59. 统一数据状态

```text
Loading
Ready
Empty
Refreshing
Stale
Error
```

---

## 60. 统一权限状态

```text
Unknown
Allowed
ReadOnly
Denied
```

---

## 61. 统一 Sync 状态

```text
Local
Syncing
Synced
Durable
Offline
Error
```

---

# Part O: Observability Hook

## 62. 每次 Client Interaction

关键操作至少携带：

```text
requestId
traceId（由 Gateway / Backend 扩展）
clientVersion
session context
resourceId / taskId where applicable
```

用于日志与 Trace 串联。

---

## 63. Frontend Error Correlation

用户看到错误时：

```text
requestId
```

必须可用于后端诊断。

---

# Part P: Hard Constraints

## 64. 架构硬约束

1. 所有用户动作必须有明确系统状态，不允许前端凭感觉判定成功。
2. Query、Command、Async Task、Realtime、Offline 必须使用不同反馈语义。
3. HTTP 接受异步任务不代表任务最终完成。
4. Task Stream 不是 Source of Truth，Query 必须能恢复最终状态。
5. Realtime 必须区分 Local / Synced / Durable。
6. WebSocket send success 不等于 Durable。
7. Offline Reconnect 必须重新验证 Session、Permission、Lifecycle。
8. PermissionChanged 必须快速反馈到所有依赖 Feature。
9. SessionReplaced 必须作为独立系统状态处理。
10. Conflict 不允许默认 Last Writer Wins 覆盖。
11. PartialSucceeded 必须显式表达。
12. Command Result 与 Event 可能同时出现，客户端更新必须幂等。
13. Target Navigation 必须使用稳定业务引用。
14. Error 必须使用统一 Error Envelope。
15. 前端用户反馈文本不得成为系统状态来源。
16. Multi-tab 本地广播只能作为优化。
17. 所有关键交互必须可通过 requestId / traceId 诊断；可重试 Mutating Command 另外使用稳定 idempotencyKey。
18. 本设计与 04、05、18、19 号设计保持一致。

---

## 65. 最终模型

```text
User Intent
↓
UI
↓
Feature Module
↓
Client SDK
↓
Command / Query / Stream
↓
Gateway
↓
Backend Domain
↓
Authoritative State
↓
Response / Event / Stream
↓
Frontend State Machine
↓
UI Feedback
```

异步：

```text
Intent
↓
Pending
↓
Accepted(taskId)
↓
Processing
↓
Succeeded / Failed
↓
Final Query
```

Realtime：

```text
Local
↓
Syncing
↓
Synced
↓
Durable
```

系统必须保证：

> 前端永远知道“当前只是本地成功、服务器已接受、正在处理、已经同步、已经持久化、发生冲突还是最终失败”，而不是把所有情况压缩成一个模糊的 Success / Error。
