# Client API & Frontend Integration Design

## 1. 目标

本设计定义官方客户端与后端系统之间的正式边界，以及桌面 Web、移动端基础体验、离线编辑、多 Tab、Realtime、Client Contract、错误恢复和前端本地状态的统一架构。

本模块解决：

> 前端如何访问后端能力，哪些接口可以暴露给浏览器，哪些内部模块必须隐藏，客户端如何统一使用 Command / Query / Event / Stream，如何处理本地 Y.Doc、离线缓存、多 Tab、Session、权限变化、长任务和错误，同时避免每个页面自己发明一套 API。

第一版产品决策已经确定：

```text
桌面 Web
= 主要完整体验

移动端
= 查看、评论、通知等基础能力

已访问 Resource
= 支持离线继续编辑

网络恢复
= CRDT 自动同步

同一设备
= 允许多 Tab

Public API
= 第一版不开放
```

---

## 2. 前端的系统定位

前端不是单纯 UI。

官方客户端至少包含：

```text
UI / UX
Editor
Local Y.Doc
Client State
Offline Cache
Realtime Client
Session Client
Permission-aware UI
Task / Stream Client
Error Recovery
Routing
```

因此前端属于：

```text
System Runtime Edge
```

它拥有本地运行状态，但不拥有后端权威业务状态。

---

## 3. Client Boundary

浏览器只通过：

```text
Client Contract Layer
```

访问后端。

推荐逻辑：

```text
Frontend
   │
   ▼
Client Contract
   │
   ├── Command
   ├── Query
   ├── Event
   └── Stream
   │
   ▼
Client Gateway / API Boundary
   │
   ▼
Backend Modules
```

浏览器不得直接访问：

```text
PostgreSQL
Search Engine
Queue
Object Storage Secret
Internal Worker
Persistence Journal
Internal Permission Service
Internal Event Bus
```

---

## 4. Internal Contract 与 Client Contract 分离

统一通信语义已经由：

```text
04-Unified-Module-Communication-Design
```

定义。

但：

```text
Internal Contract
```

和：

```text
Client Contract
```

不是同一暴露面。

例如以下内部能力不应直接暴露给浏览器：

```text
Replay Dead Letter
Write Persistence Journal
Rebuild Search Index
Trigger Compaction
Internal Permission Propagation
Internal Outbox Publish
```

浏览器只获得正式用户能力。

---

## 5. 第一版不开放 Public API

第一版 Client Contract：

```text
只服务官方客户端
```

不承诺：

```text
第三方长期兼容 SDK
Public REST API
Developer Token
Webhook Platform
External App Marketplace
```

这样第一版可以更快演进内部协议。

但 Contract 仍需：

```text
typed
versioned
testable
```

不能因为没有 Public API 就随意失控。

---

## 6. Client Gateway

客户端通过统一 Gateway 访问后端。

Gateway 负责：

```text
Authentication
Request Context
Rate Limit
Routing
Protocol Version
Error Normalization
Tracing
Client Compatibility
```

它不是：

```text
所有业务逻辑的超级服务
```

业务逻辑仍在对应后端模块。

---

## 7. Client Contract 四类交互

前端统一使用：

```text
Command
Query
Event
Stream
```

### Command

用于：

```text
创建
修改
删除
状态转换
```

### Query

用于：

```text
读取当前状态
```

### Event

表示：

```text
某件事已经发生
```

### Stream

用于：

```text
持续实时数据
```

---

## 8. Command 示例

客户端 Command：

```text
CreateResource
RenameResource
MoveResource
CreateComment
ResolveThread
ApplyChangeSet
StartAITask
CancelAITask
MarkNotificationRead
Logout
```

正文编辑是特殊情况。

Document 正文修改：

```text
Editor Transaction
↓
Local Y.Doc
↓
Realtime Stream
```

而不是每次按键调用普通 HTTP Command。

---

## 9. Query 示例

客户端 Query：

```text
GetCurrentAccount
GetProjectTree
GetResourceMetadata
GetPermission
ListResourceThreads
ListNotifications
GetAITask
GetHistory
SearchResources
```

Query：

```text
不得产生业务副作用
```

---

## 10. Event 示例

前端可能收到：

```text
ResourceRenamed
ResourceMoved
PermissionChanged
CommentCreated
ThreadResolved
NotificationCreated
AITaskCompleted
SessionReplaced
```

Event 表示：

```text
事实已发生
```

不是客户端请求。

---

## 11. Stream 示例

客户端 Stream：

```text
Yjs Sync
Awareness
Comment Realtime Events
Notification Events
AI Output
Task Progress
System Control Events
```

Stream 断开后：

```text
必须可以通过 Query / Sync 恢复
```

不能让 Stream 成为唯一真相。

---

## 12. Transport 不统一成一种

语义统一：

```text
Command / Query / Event / Stream
```

不代表所有数据都必须走：

```text
同一个 WebSocket
```

合理组合：

```text
HTTP / RPC
= Command / Query

WebSocket
= Realtime Stream

Direct Object Storage Upload
= Asset Data Plane
```

具体 Transport 由本地 AI 根据现有技术栈实现。

---

## 13. Client SDK

官方前端应使用统一：

```text
Client SDK
```

或等价 Contract Layer。

页面组件不能自己散落：

```text
fetch("/api/xxx")
fetch("/api/yyy")
new WebSocket(...)
```

形成第二套网络逻辑。

---

## 14. Client SDK 职责

至少负责：

```text
Auth Context
Command
Query
Error Mapping
Request ID
Trace Context
Retry Policy
Abort / Cancel
Realtime Connection
Subscription
Task Stream
Protocol Version
```

---

## 15. 业务组件不得知道 Transport 细节

例如 Comment UI：

```text
commentClient.create(...)
```

而不是：

```text
fetch + JSON + 手动拼 Authorization
```

Editor Realtime：

```text
resourceRealtime.subscribe(resourceId)
```

而不是各组件自己建立 WebSocket。

---

## 16. Typed Contract

前后端 Contract 必须有统一类型来源。

例如可以采用：

```text
OpenAPI
JSON Schema
Protobuf
IDL
Code Generation
```

本设计不指定具体方案。

目标是：

```text
TypeScript
Python
Rust
```

尽可能从同一个 Contract Source 获得一致类型。

---

## 17. 禁止手抄双份类型

不应长期维护：

```text
frontend/types.ts
backend/schema.py
```

两份人工同步定义。

否则容易出现：

```text
字段名不一致
枚举漂移
可选字段不同
版本不兼容
```

---

## 18. Contract Version

Client Contract 必须支持：

```text
version
```

尤其：

```text
Realtime Protocol
Event Schema
Critical Command
```

需要考虑旧客户端短时间存在。

---

## 19. Desktop Web

桌面 Web 是第一版完整客户端。

包含：

```text
Workspace / Project Navigation
Full Resource Editing
Realtime Collaboration
Comments
Notifications
History
Search
AI
Import / Export
Account Settings
```

---

## 20. Mobile

移动端第一版属于：

```text
Companion Experience
```

主要支持：

```text
查看 Resource
查看 Project
评论
回复
@Mention
通知中心
Share Link Read
基础 Account
```

第一版不承诺：

```text
完整富文本编辑
复杂 Code Editor
多 Resource AI Refactor
大型 Import / Export
复杂 History Diff
```

---

## 21. Responsive 与 Mobile Client

第一版可以通过：

```text
Responsive Web
```

完成移动端基础体验。

不要求立即开发：

```text
Native iOS
Native Android
```

但后端 Client Contract 不应只适配桌面 DOM。

---

## 22. Frontend State 分类

前端状态必须分为：

```text
Server State
Local UI State
Realtime State
Editor State
Offline State
```

不能全部塞进一个全局 Store。

---

## 23. Server State

例如：

```text
Project Tree
Resource Metadata
Permission
Comments
Notifications
Task Status
Account
```

它们来自后端 Query / Event。

可以缓存。

但后端仍是 Source of Truth。

---

## 24. Local UI State

例如：

```text
sidebar open
selected tab
dialog state
panel width
temporary filter
hover
```

这些只属于前端。

不应写入后端。

---

## 25. Realtime State

例如：

```text
connection status
subscription status
awareness
remote cursors
stream progress
```

它们与连接生命周期相关。

不能与 PostgreSQL 权威状态混为一谈。

---

## 26. Editor State

Document Editor：

```text
ProseMirror State
Local Y.Doc
Selection
Composition
Undo Context
```

属于 Editor Runtime。

不能每次变化都同步进普通全局 React Store。

---

## 27. Offline State

至少包括：

```text
cached resource content
pending local Yjs updates
last sync state
offline availability
```

离线状态需要独立管理。

---

## 28. Source of Truth 规则

第一版统一：

```text
Resource Content
→ Local Y.Doc while editing
→ CRDT convergence with server

Resource Metadata
→ Backend

Permission
→ Backend

Comments
→ PostgreSQL backend

Notification
→ PostgreSQL backend

UI State
→ Client

Presence
→ Awareness
```

避免同一个对象出现两套可写状态。

---

## 29. Desktop Resource 打开流程

桌面打开 Resource：

```text
Route
↓
Query Resource Metadata
↓
Permission Check
↓
Create / Load Local Resource Runtime
↓
Load Local Cached Yjs State if available
↓
Open Realtime Subscription
↓
Yjs State Vector Sync
↓
Editor Ready
```

---

## 30. Local-first Editor

用户输入：

```text
Keyboard
↓
Editor Transaction
↓
Local Y.Doc
↓
UI immediate
↓
Realtime send
```

用户输入不等待：

```text
HTTP
PostgreSQL
Checkpoint
```

---

## 31. 已访问 Resource 离线能力

第一版只保证：

> 已经成功打开并缓存过的 Resource，可以离线继续编辑。

并不保证：

```text
从未打开的 Resource
```

离线时可以首次完整加载。

---

## 32. Offline Open

离线时打开已缓存 Resource：

```text
Local Cache
↓
Local Y.Doc
↓
Editor
```

UI 必须明确：

```text
Offline
```

而不是假装已经同步服务器。

---

## 33. Offline Edit

离线编辑：

```text
Local Y.Doc
↓
Persist local state
```

本地修改不得只存在内存。

浏览器刷新 / Crash 后应尽量恢复。

---

## 34. Offline Persistence

浏览器本地可以使用：

```text
IndexedDB
```

或等价持久存储。

具体库由本地 AI 选择。

不应依赖：

```text
localStorage
```

保存大型 Yjs State。

---

## 35. Offline Sync

网络恢复：

```text
Reconnect
↓
Authenticate
↓
Subscribe Resource
↓
State Vector Exchange
↓
Bidirectional Diff
↓
CRDT Merge
```

不是：

```text
上传本地完整文档覆盖服务器
```

---

## 36. Offline 与 Permission Change

用户离线期间：

```text
Edit 权限
→ Read
```

用户本地仍可能产生修改。

恢复网络时：

```text
Permission Check
↓
拒绝上传正式写入
```

但客户端必须保留本地内容。

允许：

```text
Copy
Export
Wait for Permission Restore
```

---

## 37. Offline 与 Resource Delete

离线期间 Resource 被 Trash / Delete。

客户端重连：

```text
不得偷偷创建同名新 Resource
```

应提示：

```text
目标已删除 / 不可写
```

并保护本地未同步内容。

---

## 38. Offline 与 Session Replacement

设备 A 离线编辑。

设备 B 登录后根据单设备规则替换 Session A。

A 恢复网络：

```text
Session Invalid
```

不能直接上传。

用户重新登录后：

```text
重新检查 Permission
```

再决定是否可以同步。

---

## 39. Offline Storage Security

本地缓存属于：

```text
用户设备上的数据副本
```

退出登录后需要按安全策略处理。

第一版建议：

```text
Session Logout
↓
清理敏感 Account Cache
```

但离线未同步内容不能在没有确认的情况下被静默销毁。

---

## 40. Logout 与 Unsynced Changes

如果用户点击 Logout，而当前存在：

```text
unsynced local changes
```

客户端必须明确提示。

例如：

```text
当前有尚未同步的修改
```

允许：

```text
Cancel Logout
Export Local Copy
Discard and Logout
```

不能直接清掉。

---

## 41. 多 Tab

同一浏览器设备允许：

```text
多个 Tab
```

同时使用。

这些 Tab 属于：

```text
同一个 Account Session
```

不会互相踢下线。

---

## 42. 多 Tab Session

Session 粒度是：

```text
Device / Browser Session
```

不是：

```text
Tab
```

例如：

```text
Tab A
Tab B
Tab C
```

共享同一个认证 Session。

---

## 43. 多 Tab 同 Resource

允许多个 Tab 打开：

```text
同一个 Resource
```

必须保持正确。

不能因为两个 Tab 同时编辑就：

```text
产生本地覆盖
```

Yjs 可以正常合并。

---

## 44. 多 Tab Realtime 优化

可以采用：

```text
每 Tab 独立 Realtime
```

作为简单正确基线。

以后可以通过：

```text
SharedWorker
BroadcastChannel
Leader Tab
```

共享部分连接和缓存。

第一版不要为了省一个 WebSocket 引入高风险复杂度。

---

## 45. BroadcastChannel

多 Tab 可以使用：

```text
BroadcastChannel
```

同步：

```text
Session replaced
Logout
Notification badge
local cache invalidation
```

但 BroadcastChannel：

```text
不是权威状态
```

只是本设备优化。

---

## 46. 多 Tab Logout

任何 Tab 主动 Logout：

```text
唯一 Session 失效
```

其他 Tab 应快速进入 Logged Out。

不能只有点击 Logout 的那个 Tab 下线。

---

## 47. 多 Tab Session Replacement

新设备登录后：

```text
当前设备的 Session
```

整体失效。

本设备所有 Tab：

```text
全部下线
```

---

## 48. Client Cache

Query 数据可以缓存。

例如：

```text
Project Tree
Resource Metadata
Permission
Comments
Notifications
Search Results
```

但 Cache 必须有：

```text
key
scope
stale policy
invalidation
```

---

## 49. Cache Key

至少包含必要 Scope：

```text
workspaceId
projectId
resourceId
user context
query params
```

权限敏感数据不能跨 Account Cache 复用。

---

## 50. Cache Invalidation

Event 到达后：

```text
invalidate
update cache
refetch
```

由数据类型决定。

例如：

```text
ResourceRenamed
→ update Resource Metadata cache

PermissionChanged
→ invalidate Permission + dependent queries
```

---

## 51. Event Miss

前端可能漏 Event。

因此 Cache 不能只靠：

```text
Event 永远完整
```

长期正确。

需要：

```text
focus refetch
reconnect refetch
TTL
explicit query
```

等恢复机制。

---

## 52. Permission-aware UI

Frontend 根据：

```text
current capabilities
```

控制 UI。

例如：

```text
canEdit
canComment
canManage
```

决定按钮显示 / 禁用。

但前端只是体验层。

服务器仍然最终鉴权。

---

## 53. 权限变化

用户编辑过程中：

```text
Edit
→ Read
```

客户端收到：

```text
PermissionChanged
```

后：

```text
Editor 进入 Read-only
Command UI Disable
Realtime Write Stop
```

不能等刷新页面才变化。

---

## 54. Optimistic UI

适合：

```text
Rename
Comment Create
Notification Read
```

等操作做 Optimistic UI。

但必须支持：

```text
rollback
server rejection
conflict
```

不能永久假设成功。

---

## 55. 不适合 Optimistic 的操作

高风险操作不应轻率 Optimistic：

```text
Permanent Delete
Owner Transfer
Permission Change
Account Delete
Large Import
AI Multi-resource Apply
```

这些应等待服务端正式确认。

---

## 56. Request Identity

每个 Client Command / Query 至少携带或获得：

```text
requestId
```

`requestId` 用于：

```text
trace
diagnostic
request / response correlation
```

所有可能安全重试的 Mutating Command 另外使用：

```text
idempotencyKey
```

---

## 57. Client Generated Identity

客户端可以生成 `requestId` 和 `idempotencyKey`。

```text
同一个逻辑 Command 重试
→ idempotencyKey 保持相同
→ 每个网络 attempt 使用新的 requestId
```

不得再用 `requestId` 同时承担两种语义。

---

## 58. Abort

前端 Query / Command 应支持：

```text
Abort / Cancel
```

例如：

```text
route changed
search query replaced
dialog closed
```

避免无意义请求持续占用资源。

---

## 59. Retry

Client SDK 统一定义 Retry。

可以自动 Retry：

```text
transient network error
temporary unavailable
safe idempotent query
explicitly idempotent command
```

不能自动 Retry：

```text
unknown non-idempotent mutation
permission denied
validation error
```

---

## 60. Backoff

网络 Retry / Reconnect 使用：

```text
exponential backoff
+
jitter
```

避免故障恢复时形成雪崩。

---

## 61. Client Error Model

前端只处理统一错误分类：

```text
Validation
Authentication
Permission
NotFound
Conflict
RateLimit
Timeout
Unavailable
DependencyFailure
Internal
```

具体模块错误通过：

```text
errorCode
```

进一步区分。

---

## 62. Error UX

错误必须映射到用户能理解的行为。

例如：

```text
SessionReplaced
→ 你的账号已在另一台设备登录

PermissionDenied
→ 你当前没有编辑权限

Conflict
→ 内容已变化，请重新确认

RateLimited
→ 操作过于频繁，请稍后重试
```

不能所有错误统一显示：

```text
Something went wrong
```

---

## 63. Unknown Error

未知错误：

```text
显示通用错误
+
保留 requestId
```

让用户可以提供诊断信息。

不能把：

```text
stack trace
database error
internal path
```

直接显示给用户。

---

## 64. Route

前端 Route 不作为业务 Identity。

例如：

```text
/workspace/x/project/y/resource/z
```

只是导航表达。

真正身份仍然是：

```text
workspaceId
projectId
resourceId
```

---

## 65. Rename / Move 与 URL

Resource Rename / Move：

```text
resourceId 不变
```

如果 URL 包含名称：

```text
可以更新可读 slug
```

但旧链接应尽量通过 stable ID 仍能解析。

---

## 66. Deep Link

通知、Comment、History、AI Task 等使用：

```text
stable target reference
```

构造 Deep Link。

例如：

```text
resourceId
threadId
nodeId
taskId
```

不是保存完整脆弱 URL。

---

## 67. Resource Runtime

前端打开一个 Resource 时创建：

```text
Resource Runtime
```

它负责组合：

```text
metadata
permission
local Y.Doc
editor
realtime subscription
awareness
comments
offline state
```

---

## 68. Runtime 生命周期

建议：

```text
COLD
LOADING
READY
OFFLINE
RECONNECTING
READ_ONLY
ERROR
DISPOSED
```

具体内部状态可由本地 AI细化。

---

## 69. Runtime Disposal

Resource 关闭后：

```text
unsubscribe realtime
release editor
flush local cache
dispose awareness
```

但：

```text
离线缓存
```

可以继续保留。

---

## 70. Resource Runtime 不放全局 Store

大型 Editor Runtime：

```text
Y.Doc
EditorView
ProseMirror State
```

不应整体放进通用序列化 Store。

否则容易：

```text
性能差
重复渲染
生命周期混乱
```

---

## 71. Editor Adapter

不同 Resource Type 提供：

```text
Client Resource Adapter
```

例如：

```text
Document Client Adapter
Code Client Adapter
Markdown Client Adapter
Text Client Adapter
```

负责：

```text
create runtime
render
sync
offline
find
history preview
```

---

## 72. Resource Type Registry

前端和后端都应围绕：

```text
Resource Type Registry
```

扩展。

新增 Resource Type 不应要求：

```text
修改几十个 switch
```

---

## 73. Current Resource Find

当前 Resource：

```text
Ctrl + F
```

直接使用本地 Editor State。

不调用 Global Search。

---

## 74. Global Search

Global Search：

```text
Client Query
↓
Search Service
```

返回：

```text
ResourceRef / NodeRef
```

点击后：

```text
Route
↓
Resource Runtime
↓
resolve target
```

---

## 75. AI Task Client

AI UI：

```text
Start Task Command
↓
taskId
↓
Task Stream
↓
Progress / Output
↓
ChangeSet Query
↓
Preview
↓
Apply Command
```

Stream 丢失后：

```text
GetAITask
```

可以恢复。

---

## 76. Import / Export Client

大型 Import / Export：

```text
Start Command
↓
taskId / sessionId
↓
Progress Stream
↓
Query Result
```

浏览器关闭后：

```text
任务继续
```

---

## 77. Notification Client

Notification Center：

```text
Query Notifications
+
Account Event Stream
```

Stream 负责即时更新。

Query 负责恢复真相。

---

## 78. Comment Client

Comment：

```text
Query Threads
+
Resource Event Stream
```

创建：

```text
Command
```

TextRange Comment 由前端把：

```text
NodeRef
RelativePosition
```

提交给后端。

---

## 79. Asset Upload Client

Asset 上传：

```text
CreateUpload Command
↓
Upload Session
↓
Direct Object Storage Upload
↓
CompleteUpload Command
```

大文件二进制不经过普通 Client API JSON。

---

## 80. Upload Progress

上传进度：

```text
本地 upload transport
```

直接计算。

Asset Processing：

```text
Task / Event
```

更新。

两者不能混成一个百分比假装精确。

---

## 81. Session Client

Client SDK 统一处理：

```text
Authenticated
Expired
Replaced
LoggedOut
Disabled
```

页面组件不自己判断：

```text
401
```

属于哪种登录状态。

---

## 82. Session Replaced

收到：

```text
SessionReplaced
```

后客户端：

```text
stop authenticated requests
close realtime
protect unsynced local edits
show login state
broadcast to tabs
```

---

## 83. Auth Redirect

登录后：

```text
returnTo
```

只允许系统安全 Route。

不能允许任意外部 URL。

---

## 84. Startup

客户端启动流程建议：

```text
Boot
↓
Load Local Session Hint
↓
Validate Current Session
↓
Load Account
↓
Connect Account Stream
↓
Restore Route
↓
Load Required Server State
```

Session Validation 是最终依据。

---

## 85. Cold Start 与 Cached UI

可以先展示：

```text
cached shell
recent project names
recent resource
```

加速体验。

但权限敏感操作：

```text
必须等待当前 Session / Permission 确认
```

---

## 86. Skeleton 与 Loading

前端应明确区分：

```text
Loading
Empty
Error
Offline
Permission Denied
Deleted
```

不能所有状态都显示同一个 Spinner。

---

## 87. Network Status

客户端应维护：

```text
Online
Offline
Degraded
Reconnecting
```

但：

```text
navigator.onLine
```

不能作为唯一依据。

需要结合实际 API / Realtime 状态。

---

## 88. Degraded

例如：

```text
Realtime Down
HTTP OK
```

客户端可以进入：

```text
Degraded
```

并提示：

```text
正在重新连接
```

而不是把整个应用判定离线。

---

## 89. Realtime Connection

第一版可以：

```text
一个主要 WebSocket
```

复用多个 Resource Subscription。

但 Client Runtime 必须支持：

```text
transport pool
```

未来 Hot Resource 可拆独立连接。

---

## 90. Subscription

前端订阅使用：

```text
subscriptionId
resourceId
```

明确生命周期。

打开：

```text
subscribe
```

关闭：

```text
unsubscribe
```

不能只靠 Socket 断开统一清理。

---

## 91. Reconnect Subscription

WebSocket 重连后：

```text
重新认证
↓
重新订阅当前 Resource
↓
Yjs State Vector Sync
↓
恢复 Awareness
↓
恢复 Event Stream
```

---

## 92. Awareness

Presence / Cursor / Selection：

```text
Awareness
```

只存在在线协作上下文。

不持久化。

Reconnect 后重新广播当前状态。

---

## 93. Awareness 优先级

Client 发送：

```text
正文 Yjs Update
```

优先级高于：

```text
cursor
selection
typing state
```

网络拥塞时 Awareness 可以丢弃旧状态。

---

## 94. Client Backpressure

如果发送队列积压：

```text
Awareness
```

可以合并。

Yjs Update：

```text
不能静默丢
```

严重积压时可以：

```text
resync
```

---

## 95. Mobile Read

移动端打开 Resource：

```text
Query Metadata
↓
Read Content
↓
Render
```

可以使用：

```text
Read-only Yjs Runtime
```

或 Resource Type 提供的 Read Model。

具体由实现决定。

---

## 96. Mobile Comment

移动端必须支持：

```text
查看 Thread
Reply
Create Resource-level Comment
Node / Text 评论如果 UI 可可靠选择则支持
```

第一版不强制实现复杂文本范围选择体验。

---

## 97. Mobile Notification

移动端支持完整：

```text
Notification Center
Unread
Jump Target
```

但第一版不做：

```text
OS Push Notification
```

---

## 98. Mobile Offline

第一版移动端可以缓存已查看内容用于：

```text
read
```

但完整离线编辑能力主要以桌面 Web 为第一目标。

后端 Contract 不阻止以后增强。

---

## 99. Accessibility

前端 Contract 和 UI State 设计不能把关键操作仅绑定：

```text
mouse hover
color
drag
```

完整 UI 阶段需要支持：

```text
keyboard
focus
ARIA
screen reader
```

本模块只定义架构要求。

---

## 100. Localization

所有用户可见错误和状态：

```text
errorCode
↓
frontend localization
```

后端不返回写死中文作为唯一逻辑。

前端可以根据 Locale 展示。

---

## 101. Client Telemetry

前端上报：

```text
uncaught error
route error
realtime reconnect
sync failure
editor crash
task stream failure
performance sample
```

不能上传：

```text
完整正文
完整密码
Token
完整 AI Prompt
```

---

## 102. Client Version

每个请求 /连接可以携带：

```text
clientVersion
```

用于：

```text
compatibility
diagnostic
rollout
```

---

## 103. Unsupported Client

未来 Contract 升级时：

```text
过旧客户端
```

可以返回：

```text
ClientUpgradeRequired
```

Web 第一版通常刷新即可升级。

---

## 104. Frontend Release

Web 前端上线后：

```text
旧 Tab
```

仍可能长时间运行。

因此后端不能假设：

```text
网页发布后所有用户立刻刷新
```

必须保留合理兼容窗口。

---

## 105. Service Worker

第一版可以使用：

```text
Service Worker
```

缓存：

```text
app shell
static assets
```

离线 Resource 数据仍由专门 Offline Store 管理。

不要把业务离线同步全部塞进 Service Worker。

---

## 106. App Shell

静态前端资源可：

```text
long cache
content hash
```

新版本通过：

```text
manifest / hashed asset
```

更新。

---

## 107. Local Data Migration

离线缓存 Schema 也会升级。

必须支持：

```text
local schema version
migration
fallback
cleanup
```

不能前端升级后直接无法读取旧 Yjs Cache。

---

## 108. Corrupt Local Cache

如果本地缓存损坏：

```text
不能覆盖服务器
```

应：

```text
quarantine / discard corrupt cache
↓
reload from server
```

如果本地可能含未同步修改：

```text
先尝试导出 / recovery
```

---

## 109. Multiple Account Cache

虽然第一版一个浏览器 Session 只登录一个 Account：

本地缓存仍必须按：

```text
userId
workspaceId
resourceId
```

隔离。

不能让不同账号登录后看到前一个账号缓存正文。

---

## 110. Logout Cache

正常 Logout：

```text
清理该 Account 的敏感 Query Cache
close realtime
clear session state
```

Resource Offline Cache 的处理必须考虑：

```text
unsynced changes
```

不能无确认删除。

---

## 111. Share Link Client

匿名 Share 页面：

```text
独立 Anonymous Read Context
```

不要求正式 Account Session。

只能调用：

```text
Share Read Contract
```

不能复用正式登录用户的完整 API Surface。

---

## 112. Anonymous Client Capability

匿名 Client 只获得：

```text
Read Resource
必要 Asset Read
只读 Realtime（如果启用）
```

不能访问：

```text
Comment
Notification
AI
History Restore
Permission
Member
```

---

## 113. Logged-in Share

已登录用户打开 Share Link：

```text
Client
```

使用 Account Permission 重新解析。

如果正式权限更高：

```text
显示正式权限能力
```

---

## 114. Security Boundary

Client 永远视为：

```text
Untrusted
```

即使是官方前端。

后端不能因为：

```text
按钮被隐藏
```

就跳过权限检查。

---

## 115. Client Input Validation

前端可以做：

```text
early validation
```

改善体验。

后端仍必须再次验证。

---

## 116. Protocol Payload

普通业务 Payload：

```text
typed structured data
```

Yjs：

```text
binary
```

Asset：

```text
direct binary upload
```

不要把：

```text
Yjs Update
```

Base64 塞进普通业务 JSON 作为长期方案。

---

## 117. Large Payload

大型数据：

```text
Asset
Export
Import
Large Snapshot
```

使用：

```text
Object Storage / Stream / File Transfer
```

Client Contract 只传：

```text
reference
metadata
task
```

---

## 118. BFF 边界

如果实现采用：

```text
Backend for Frontend
```

可以存在。

但它的职责是：

```text
client aggregation
contract adaptation
auth context
```

不是复制全部 Domain Logic。

---

## 119. GraphQL / REST / RPC

本设计不要求用户决策：

```text
GraphQL
REST
RPC
```

这是实现选择。

只要满足：

```text
typed contract
Command / Query semantics
versioning
error model
observability
```

即可。

---

## 120. Frontend Repository Boundary

可以：

```text
monorepo
```

也可以：

```text
separate packages
```

但推荐至少有明确：

```text
client-contract
client-sdk
resource-adapters
ui
editor
```

边界。

具体目录由本地 AI 根据项目结构设计。

---

## 121. UI 不直接调用 Domain Internal

UI Component：

```text
Button
Dialog
Sidebar
Editor Toolbar
```

只能调用：

```text
Application Client Layer
```

不能直接：

```text
import raw websocket
import postgres model
import internal event type
```

---

## 122. Feature Module

前端可按：

```text
auth
workspace
resource
editor
comment
notification
history
search
ai
asset
```

组织 Feature。

但所有 Feature 共享：

```text
Client SDK
Session
Contract
Error
Telemetry
```

---

## 123. Cross-feature Coordination

例如：

```text
PermissionChanged
```

同时影响：

```text
Editor
Comment
AI
Toolbar
```

应通过：

```text
central application event / capability state
```

协调。

不要每个 Feature 自己重复监听同一原始消息并产生不同逻辑。

---

## 124. Local Application Event

前端可以有自己的：

```text
Application Event
```

例如：

```text
CurrentPermissionChanged
SessionReplaced
ResourceRuntimeDisposed
```

用于模块解耦。

这些不是后端业务 Event 的替代品。

---

## 125. Client Error Boundary

UI 需要：

```text
page-level
feature-level
editor-level
```

Error Boundary。

一个 Comment Panel 崩溃：

```text
不应把整个 Editor 一起白屏
```

---

## 126. Editor Crash Recovery

Editor 发生异常时：

```text
Local Y.Doc
```

仍应尽量保存。

UI 可以：

```text
reload editor runtime
```

而不是丢掉未同步内容。

---

## 127. Command Pending State

前端对 Command 统一处理：

```text
idle
pending
success
error
```

避免按钮被重复点击。

如果 Command 支持幂等：

```text
重复点击
```

也不会造成重复业务结果。

---

## 128. Long Task UX

长任务不能表现为：

```text
按钮转圈几分钟
```

统一：

```text
Task Created
↓
Task Panel / Notification
↓
Background Progress
↓
Result
```

用户可以离开页面。

---

## 129. Background Task Resume

重新打开应用：

```text
Query running tasks
```

恢复：

```text
AI
Import
Export
Reindex if visible to admin
```

等任务状态。

---

## 130. Client Permission Cache

Permission 可以短缓存。

但：

```text
PermissionChanged
SessionReplaced
ResourceMoved
```

后必须失效。

高风险 Command：

```text
永远由服务器重新检查
```

---

## 131. Client History Preview

History Preview 使用：

```text
isolated read-only runtime
```

不能替换当前编辑 Resource Runtime。

关闭 Preview：

```text
回到 Current Runtime
```

当前协作不停。

---

## 132. Client ChangeSet Preview

AI ChangeSet Preview：

```text
read-only diff model
```

不能在用户只是浏览 Diff 时提前修改 Local Y.Doc。

只有：

```text
Apply Success
```

后当前 Runtime 通过正常 Realtime 收到正式变化。

---

## 133. Import Preview

Import Preview：

```text
Import Plan
```

只是计划。

前端不能因为 Preview 就提前创建本地正式 Resource。

---

## 134. Offline Feature Matrix

第一版明确：

```text
已缓存 Resource Read
= Yes

已缓存 Resource Edit
= Yes

CRDT Local Edit
= Yes

Reconnect Auto Sync
= Yes

首次打开未缓存 Resource
= No

离线创建 Workspace
= No

离线创建 Project
= No

离线 Permission Management
= No

离线 Invite
= No

离线 Account Operation
= No
```

---

## 135. Mobile Feature Matrix

第一版明确：

```text
Resource Read
= Yes

Comments
= Yes

Notifications
= Yes

Share Read
= Yes

Basic Account
= Yes

Full Rich Document Editing
= No guarantee

Complex Code Editing
= No

Large Import / Export
= No

Multi-resource AI Refactor
= No
```

---

## 136. Browser Support

桌面 Web 应明确支持：

```text
现代 Chromium
现代 Safari
现代 Firefox
```

具体最低版本由实现阶段确定。

不能依赖单一浏览器私有 API 而没有降级策略。

---

## 137. Storage Quota

浏览器本地 Offline Cache 受：

```text
browser storage quota
```

限制。

客户端必须处理：

```text
quota exceeded
eviction
storage unavailable
```

不能假设 IndexedDB 无限。

---

## 138. Cache Eviction

离线 Resource Cache 可以按：

```text
recent use
size
pinned status
unsynced changes
```

清理。

拥有：

```text
unsynced changes
```

的 Resource 不得自动淘汰。

---

## 139. Offline Pin

第一版可以把：

```text
已访问过 Resource
```

自动缓存。

以后可以增加：

```text
Available Offline
```

用户显式 Pin。

第一版不强制 UI 提供该功能。

---

## 140. Client Storage Cleanup

系统应提供：

```text
storage usage
clear cached offline data
```

等基础能力。

但清理前必须保护：

```text
unsynced local changes
```

---

## 141. Sync Status

Editor UI 至少需要表达：

```text
Local
Syncing
Synced
Offline
Read-only
Error
```

Resource Runtime 必须能够接收 Realtime Protocol 的 acceptance / durable watermark，并据此内部判断 `Synced` 与 `Durable`。

是否在 UI 中直接展示 `Durable` 由 UI / UX 决定，但内部状态不得靠 `WebSocket.send()`、网络在线状态或本地时间猜测。

用户不需要理解底层 Journal 才能使用产品。

---

## 142. Synced 与 Durable

客户端不能把：

```text
已发送给服务器
```

错误显示为：

```text
一定已经 Durable
```

如果产品展示保存状态，需要遵守：

```text
Local
Synced
Durable
```

既有定义。

---

## 143. No Save Button

第一版正文编辑继续采用：

```text
Auto Sync
```

不设计传统：

```text
Save
```

按钮。

用户输入后：

```text
Local-first
+
background sync
```

---

## 144. Frontend Test Boundary

至少需要：

```text
Contract Test
Client SDK Test
Resource Runtime Test
Offline Test
Reconnect Test
Multi-tab Test
Permission Change Test
Session Replacement Test
Editor Integration Test
```

---

## 145. Contract Test

前端和后端 CI 应验证：

```text
schema compatibility
enum compatibility
required field
protocol version
```

防止后端上线后直接把前端打坏。

---

## 146. Offline Test

至少覆盖：

```text
edit then disconnect
disconnect then edit
refresh while offline
browser crash
reconnect
permission downgraded offline
session replaced offline
resource deleted offline
```

---

## 147. Multi-tab Test

至少覆盖：

```text
same session multiple tabs
same resource multiple tabs
logout one tab
session replaced
notification update
local cache update
```

---

## 148. Reconnect Test

至少覆盖：

```text
short network loss
long network loss
gateway restart
worker restart
reconnect storm
state vector resync
```

---

## 149. Observability

至少监控客户端：

```text
app load
route load
api latency
api error
websocket connect
websocket reconnect
subscription failure
yjs sync failure
offline cache failure
indexeddb quota
editor crash
unsynced resource count
task stream disconnect
session replaced
multi-tab sync failure
```

---

## 150. 第一版不做

第一版不实现：

```text
Public API
Third-party SDK
Webhook Platform
Native Mobile App
完整移动端编辑器
完整离线 Workspace
离线 Project 创建
离线 Permission
离线 Invite
复杂 P2P Sync
Browser-to-Browser Direct Sync
强制所有 Transport 走 WebSocket
自研前端状态框架
```

---

## 151. 核心验收场景

### 场景 1：桌面编辑

用户打开 Document。

结果：

```text
Metadata
↓
Permission
↓
Local Y.Doc
↓
Realtime Sync
↓
Editor
```

输入立即响应，不等待 HTTP Save。

---

### 场景 2：网络断开

已经打开的 Resource 断网。

结果：

- Editor 继续可用
- Local Y.Doc 继续记录修改
- UI 显示 Offline
- 本地状态持久化

---

### 场景 3：恢复网络

重新联网。

结果：

```text
Reconnect
↓
Permission Check
↓
State Vector Diff
↓
CRDT Merge
```

不会完整覆盖服务器文档。

---

### 场景 4：离线期间降权

用户离线编辑时被降为 Read。

恢复后：

- 不上传正式写入
- 本地修改保留
- UI 进入 Read-only
- 可以复制 / 导出本地内容

---

### 场景 5：多 Tab

Tab A 和 Tab B 打开不同 Resource。

结果：

```text
同一个 Session
```

两个 Tab 都正常工作。

不会互相踢出。

---

### 场景 6：同 Resource 多 Tab

Tab A 和 Tab B 同时打开 Resource X。

两个 Tab 都编辑。

结果：

```text
Yjs 最终收敛
```

不产生完整文档覆盖。

---

### 场景 7：新设备登录

Mac 浏览器多个 Tab 正在使用。

另一台设备登录。

结果：

- 当前 Mac Session 被替换
- 所有 Tab 快速下线
- Realtime 断开
- 未同步本地内容得到保护

---

### 场景 8：Comment Event 丢失

Comment Panel 漏掉实时 Event。

用户重连。

结果：

```text
Query Threads
```

恢复真实状态。

---

### 场景 9：AI Stream 断开

AI Task 仍在运行，但 WebSocket 断开。

结果：

- Task 不丢
- 重连后 GetAITask
- 恢复 Progress / Result

---

### 场景 10：Asset Upload

大文件上传。

结果：

```text
Client SDK
↓
Create Upload
↓
Direct Object Storage
↓
Complete Upload
```

API Server 不代理整个二进制。

---

### 场景 11：Permission Change

Resource 打开时权限 Edit → Read。

结果：

- UI 立即 Disable 编辑
- Editor Read-only
- 服务器拒绝旧写请求
- Comment / AI 按当前 capability 更新

---

### 场景 12：Resource Rename

Resource Rename。

结果：

- Route 可以更新
- resourceId 不变
- 当前 Runtime 不重建 Y.Doc
- Comment / Notification Deep Link 不失效

---

### 场景 13：History Preview

用户打开历史版本。

结果：

- 创建独立只读 Preview
- 当前 Realtime Runtime 继续运行
- 关闭 Preview 回到最新内容

---

### 场景 14：Offline Cache 损坏

本地 Yjs Cache 损坏。

结果：

- 不上传损坏状态覆盖服务器
- 正常从服务器 Reload
- 如可能含本地修改则先进入 Recovery

---

### 场景 15：移动端

手机打开 Resource。

结果：

- 可查看
- 可评论
- 可看通知
- 不要求加载完整桌面编辑器能力

---

### 场景 16：匿名 Share

匿名用户打开 Share Link。

结果：

- 使用 Anonymous Read Contract
- 不建立正式 Account Session
- 不暴露 Comment / AI / Permission API

---

### 场景 17：后端 Error

后端返回：

```text
SessionReplaced
```

结果：

前端显示明确：

```text
你的账号已在另一台设备登录
```

而不是通用 401。

---

### 场景 18：旧 Web Tab

前端发布新版本后，用户旧 Tab 仍开着。

结果：

- 后端保持合理兼容窗口
- Critical Breaking Change 有 protocol / version 处理
- 不立即随机崩溃

---

### 场景 19：浏览器 Storage 满

IndexedDB 接近 Quota。

结果：

- 监测失败
- 清理安全 Cache
- 不删除 Unsynced Resource
- 提示用户释放空间或同步

---

### 场景 20：Client Telemetry 故障

Telemetry Endpoint 不可用。

结果：

- 应用继续运行
- Telemetry 使用有界队列或丢弃
- 不因为监控阻塞用户操作

---

## 152. 本地 AI 实现自由度

本设计不规定：

- REST / GraphQL / RPC 的具体选择
- Client SDK 具体目录
- React Query / SWR / 自研 Query Layer
- Zustand / Redux / 其他 UI State Tool
- IndexedDB Library
- BroadcastChannel 封装库
- WebSocket Library
- OpenAPI / Protobuf / JSON Schema 的具体 IDL
- Service Worker Library
- Resource Runtime 类结构
- Mobile Responsive Framework
- API Gateway 产品

本地 AI可以根据现有项目技术栈与代码规模选择。

但必须满足本设计的 Contract、一致性、离线、多 Tab、Session、Realtime、安全和恢复要求。

---

## 153. 架构硬约束

1. 桌面 Web 是第一版完整客户端。
2. 移动端第一版只保证查看、评论、通知等基础能力。
3. 第一版不开放 Public API。
4. 浏览器只能通过 Client Contract / Gateway 访问后端。
5. Internal Contract 与 Client Contract 必须分离。
6. 前端统一遵守 Command / Query / Event / Stream 语义。
7. UI Feature 不直接自行创建零散网络协议。
8. Client Contract 必须 typed、versioned、testable。
9. Resource 正文使用 Local Y.Doc 作为编辑时本地状态。
10. 用户输入不等待网络或 PostgreSQL。
11. 已访问 Resource 必须支持离线继续编辑。
12. Offline Edit 必须持久到本地存储，不只存在内存。
13. Reconnect 使用 Yjs State Vector / CRDT Diff 自动同步。
14. 不允许通过完整本地文档覆盖服务器 Current State。
15. Offline Permission 变化后必须重新鉴权。
16. 权限失效时本地未同步内容不得静默删除。
17. 同一设备允许多个 Tab。
18. Tab 不是 Session，多个 Tab 共享同一设备登录 Session。
19. 同 Resource 多 Tab 必须保持正确收敛。
20. Session Replacement 必须影响本设备所有 Tab。
21. Server State、UI State、Realtime State、Editor State、Offline State 必须职责分离。
22. Permission-aware UI 只是体验层，后端仍最终鉴权。
23. Stream 不是 Source of Truth，Reconnect 后必须可 Query / Sync 恢复。
24. Asset 大文件使用 Direct Upload，不走普通业务 JSON。
25. Deep Link 使用稳定业务引用，不使用脆弱完整 URL 作为唯一身份。
26. History Preview / ChangeSet Preview 必须是隔离只读 Runtime。
27. Client Cache 必须按 user / workspace / resource 正确隔离。
28. Logout 前必须处理 Unsynced Changes。
29. Client Error 必须使用统一 Error Model。
30. Client / Frontend Integration 遵守 Unified Module Communication Design 和 Realtime Collaboration Protocol Design。

---

## 154. 最终模型

```text
                       Official Client
                            │
               ┌────────────┼────────────┐
               ▼            ▼            ▼
              UI        Resource Runtime  Offline Store
               │            │            │
               │            ├── Editor   ├── Cached Y.Doc
               │            ├── Y.Doc    └── Pending Local State
               │            └── Awareness
               │
               ▼
                     Client SDK
                         │
             ┌───────────┼───────────┐
             ▼           ▼           ▼
          Command      Query       Stream
             │           │           │
             └──────┬────┴────┬──────┘
                    ▼         ▼
               Client Gateway
                    │
                    ▼
               Backend Modules
```

离线：

```text
Local Y.Doc
↓
Offline Store
↓
Network Returns
↓
Session / Permission
↓
State Vector Diff
↓
CRDT Merge
```

多 Tab：

```text
One Device Session
├── Tab A
├── Tab B
└── Tab C
```

前后端边界最终统一为：

> 前端拥有交互、本地运行时和离线能力，后端拥有权威业务状态；双方通过统一 Client Contract 通信，Realtime 使用专门 Stream 子协议，离线修改通过 CRDT 收敛，而不是让每个页面、每个模块、每个 Tab 自己发明一套接口。
