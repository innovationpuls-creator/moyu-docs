# Frontend Module Contract Design

## 1. 目标

本设计定义前端功能模块与后端能力之间的正式契约边界。

本模块不负责：

```text
页面布局
视觉风格
组件样式
交互动效
信息层级
具体 UX 决策
```

这些由 UI / UX 设计负责。

本模块只负责：

> 前端需要有哪些功能模块，每个模块依赖哪些后端能力，使用哪些 Command / Query / Event / Stream，哪些状态属于前端、哪些属于后端，以及模块之间如何协作而不形成黑箱和重复状态。

---

## 2. 核心原则

前端每个业务模块必须明确：

```text
Own State
Backend Dependencies
Commands
Queries
Events
Streams
Offline Behavior
Permission Dependency
Error States
Cross-module Dependencies
```

不能只定义：

```text
“这个页面要有一个按钮”
```

而没有明确：

```text
按钮调用什么
成功后谁更新
失败后如何恢复
实时变化从哪里来
```

---

## 3. UI / UX 与 Contract 分离

统一边界：

```text
UI / UX
= 决定用户看到什么、怎么操作、怎么布局

Frontend Module Contract
= 决定这个功能需要什么系统能力，以及如何与后端交互
```

例如：

```text
“评论按钮放哪里”
```

属于 UI / UX。

而：

```text
点击评论后调用 CreateTextRangeComment
Comment 创建后通过 Resource Event Stream 更新
```

属于本设计。

---

## 4. 前端模块总览

第一版前端至少包括：

```text
Auth
Workspace
Project
Resource Tree
Resource Runtime
Document Editor
Code / Markdown / Text Editor
Comment
Notification
Search
History
AI
Asset
Import / Export
Permission / Share
Task Center
Offline / Sync
Account / Security
Trash
Mobile Companion
```

---

## 5. 模块分层

建议逻辑分层：

```text
UI Layer
↓
Feature Module
↓
Application Client Layer
↓
Client SDK
↓
Client Contract
↓
Backend
```

任何 UI 组件：

```text
不得直接访问 Backend Internal API
```

---

## 6. Feature Module

Feature Module 负责：

```text
业务功能编排
本地 feature state
调用 Client SDK
处理 Query / Command result
消费 Event / Stream
```

不负责：

```text
数据库
权限最终判断
后端事务
```

---

## 7. Shared Client Layer

以下能力必须共享：

```text
Session
Client SDK
Command
Query
Event
Stream
Error Mapping
Request / Trace Context
Realtime Connection
Offline Store
Permission Capability State
Telemetry
```

不能各 Feature 自己实现一份。

---

# Part A: Auth / Account

## 8. Auth Module

负责：

```text
注册
邮箱登录
微信登录
飞书登录
邮箱验证
密码找回
登出
Session 恢复
Session Replaced
```

---

## 9. Auth Commands

```text
RegisterWithEmail
LoginWithPassword
StartWeChatLogin
CompleteWeChatLogin
StartFeishuLogin
CompleteFeishuLogin
RequestPasswordReset
ResetPassword
Logout
```

---

## 10. Auth Queries

```text
GetCurrentAccount
GetCurrentSession
GetAccountStatus
```

---

## 11. Auth Events / Streams

```text
SessionCreated
SessionReplaced
SessionInvalidated
AccountDisabled
```

---

## 12. Auth Local State

前端只保存：

```text
auth loading state
current route intent
temporary form state
session client status
```

权威身份状态：

```text
Backend Session
```

---

# Part B: Workspace / Project / Tree

## 13. Workspace Module

负责：

```text
Workspace List
Workspace Switch
Workspace Create / Rename
Workspace Lifecycle
```

---

## 14. Workspace Commands

```text
CreateWorkspace
RenameWorkspace
RequestWorkspaceDeletion
CancelWorkspaceDeletion
```

---

## 15. Workspace Queries

```text
ListWorkspaces
GetWorkspace
GetWorkspaceCapabilities
```

---

## 16. Workspace Events

```text
WorkspaceCreated
WorkspaceRenamed
WorkspaceDeletionRequested
WorkspaceDeleted
```

---

## 17. Project Module

负责：

```text
Project List
Project Create
Rename
Archive
Restore
Trash
```

---

## 18. Project Commands

```text
CreateProject
RenameProject
ArchiveProject
UnarchiveProject
TrashProject
RestoreProject
```

---

## 19. Project Queries

```text
ListProjects
GetProject
GetProjectCapabilities
```

---

## 20. Resource Tree Module

负责：

```text
Folder Tree
Resource Tree
Create Folder
Create Resource
Rename
Move
Duplicate
Trash
Restore
```

---

## 21. Resource Tree Commands

```text
CreateFolder
RenameFolder
MoveFolder
TrashFolder
RestoreFolder

CreateResource
RenameResource
MoveResource
DuplicateResource
TrashResource
RestoreResource
```

---

## 22. Resource Tree Queries

```text
GetProjectTree
ListFolderChildren
GetResourceMetadata
```

---

## 23. Resource Tree Events

```text
FolderCreated
FolderRenamed
FolderMoved
FolderTrashed
ResourceCreated
ResourceRenamed
ResourceMoved
ResourceDuplicated
ResourceTrashed
ResourceRestored
```

---

## 24. Resource Tree State

权威状态：

```text
Backend
```

前端可以缓存：

```text
expanded folders
selected node
tree query cache
```

---

# Part C: Resource Runtime

## 25. Resource Runtime Module

每个打开的 Resource 创建：

```text
Resource Runtime
```

负责组合：

```text
Metadata
Permission
Local Y.Doc / Local Content Runtime
Realtime Subscription
Offline State
Awareness
Comments
Sync State
```

---

## 26. Resource Runtime Queries

```text
GetResourceMetadata
GetResourceCapabilities
GetResourceInitialReadState
```

---

## 27. Resource Runtime Streams

```text
Yjs Sync
Awareness
Resource Events
Permission Events
System Control Events
```

---

## 28. Resource Runtime State

可以包含：

```text
loading
ready
offline
reconnecting
readOnly
error
disposed
```

这属于前端 Runtime State。

---

# Part D: Document Editor

## 29. Document Editor Module

负责：

```text
ProseMirror / Tiptap Runtime
Local Y.Doc
Selection
Editor Transaction
Undo
Find
NodeRef
Comment Anchor Creation
Presence
```

---

## 30. Document Editor 后端交互

正文编辑：

```text
不通过普通 Command
```

主路径：

```text
Editor Transaction
↓
Local Y.Doc
↓
Realtime Stream
```

---

## 31. Document Commands

业务级编辑操作通过：

```text
Document Command
```

例如：

```text
AI Apply
Block Operation
Structured Change
```

但普通键盘输入不走业务 Command API。

---

## 32. Document Queries

主要依赖：

```text
GetResourceMetadata
GetResourceCapabilities
History Query
Comment Query
```

正文 Current State 由：

```text
Local Y.Doc
```

承担。

---

# Part E: Code / Markdown / Text

## 33. Text Resource Module

负责：

```text
Code
Markdown
Plain Text
```

不同 Resource Type 使用对应 Client Adapter。

---

## 34. Text Resource Stream

正文同步仍使用：

```text
Yjs Stream
```

例如：

```text
Y.Text
```

---

## 35. Current Resource Find

当前 Resource 内查找：

```text
只查本地 Editor Runtime
```

不调用 Global Search。

---

# Part F: Comment

## 36. Comment Module

负责：

```text
Resource Comment
Node Comment
Text Range Comment
Reply
Resolve
Reopen
Delete Tombstone
Mention
```

---

## 37. Comment Commands

```text
CreateResourceComment
CreateNodeComment
CreateTextRangeComment
ReplyComment
EditComment
DeleteComment
ResolveThread
ReopenThread
```

---

## 38. Comment Queries

```text
ListResourceThreads
GetThread
ListResolvedThreads
ListMentionCandidates
```

---

## 39. Comment Events

```text
CommentThreadCreated
CommentCreated
CommentEdited
CommentDeleted
ThreadResolved
ThreadReopened
```

---

## 40. Comment Stream

当前 Resource 打开时：

```text
Resource Event Stream
```

实时更新评论。

Stream 丢失后：

```text
重新 Query
```

恢复。

---

# Part G: Notification

## 41. Notification Module

负责：

```text
Notification Center
Unread Count
Mark Read
Mark All Read
Jump Target
```

---

## 42. Notification Commands

```text
MarkNotificationRead
MarkAllNotificationsRead
```

---

## 43. Notification Queries

```text
ListNotifications
GetUnreadNotificationCount
```

---

## 44. Notification Events

```text
NotificationCreated
NotificationRead
```

---

## 45. Notification Stream

使用：

```text
Account Event Stream
```

更新：

```text
Unread Badge
New Notification
```

---

# Part H: Search

## 46. Search Module

负责：

```text
Workspace Search
Project Search
Folder Search
Filter
Result
Target Navigation
```

---

## 47. Search Queries

```text
SearchResources
GetSearchSuggestions
```

---

## 48. Search Result

至少包含：

```text
resourceId
resourceType
name
snippet
target reference
location
```

Document 命中可带：

```text
NodeRef
```

---

## 49. Search State

前端只维护：

```text
query text
filters
result cache
pagination cursor
loading
```

Search Index 不属于前端。

---

# Part I: History

## 50. History Module

负责：

```text
Version Timeline
Named Version
Preview
Diff
Restore
```

---

## 51. History Commands

```text
CreateNamedVersion
RestoreVersion
```

---

## 52. History Queries

```text
ListHistory
GetVersion
GetHistoryPreview
GetHistoryDiff
```

---

## 53. History Events

```text
NamedVersionCreated
HistoryRestored
```

---

## 54. History Preview State

必须使用：

```text
isolated read-only runtime
```

不能替换 Current Resource Runtime。

---

# Part J: AI

## 55. AI Module

负责：

```text
AI Ask
AI Edit
Task Progress
ChangeSet
Diff
Apply
Reject
Retry
Conflict
Partial Apply
```

---

## 56. AI Commands

```text
StartAITask
CancelAITask
ApplyChangeSet
RejectChangeSet
RetryAITask
```

---

## 57. AI Queries

```text
GetAITask
GetChangeSet
GetChangePreview
ListAITasks
```

---

## 58. AI Streams

```text
AI Output
Task Progress
```

Stream 断开：

```text
GetAITask
```

恢复。

---

## 59. AI ChangeSet State

前端可以维护：

```text
selected revision
selected resources
review state
diff state
```

权威 ChangeSet：

```text
Backend
```

---

# Part K: Asset

## 60. Asset Module

负责：

```text
Upload
Progress
Processing
Preview
Download
Failure
Blocked
```

---

## 61. Asset Commands

```text
CreateUpload
CompleteUpload
CancelUpload
RetryAssetProcessing
```

---

## 62. Asset Queries

```text
GetAsset
GetAssetAccess
GetUploadStatus
GetProcessingStatus
```

---

## 63. Asset Data Path

大文件：

```text
Client
↓
Direct Object Storage Upload
```

不是：

```text
Client
↓
普通 JSON API
↓
API Server
```

---

# Part L: Import / Export

## 64. Import Module

负责：

```text
Source Upload
Preview
Import Plan
Conflict
Progress
Partial Result
Retry
```

---

## 65. Import Commands

```text
CreateImportSession
CreateImportPlan
ApplyImportPlan
CancelImport
RetryImportItem
```

---

## 66. Import Queries

```text
GetImport
GetImportPlan
GetImportProgress
GetImportResult
```

---

## 67. Export Module

负责：

```text
Format Selection
Progress
Result
Download
```

---

## 68. Export Commands

```text
CreateExport
CancelExport
RetryExport
```

---

## 69. Export Queries

```text
GetExport
GetExportProgress
GetExportResult
```

---

# Part M: Permission / Share

## 70. Permission Module

负责：

```text
Member List
Invite
Role Change
Remove Member
Owner Transfer
Share Link
```

---

## 71. Permission Commands

```text
InviteMember
ChangeMemberRole
RemoveMember
TransferOwner
CreateShareLink
UpdateShareLink
RevokeShareLink
```

---

## 72. Permission Queries

```text
ListMembers
GetResourceCapabilities
ListShareLinks
GetInviteStatus
```

---

## 73. Permission Events

```text
PermissionChanged
MemberAdded
MemberRemoved
OwnerTransferred
ShareCreated
ShareRevoked
```

---

## 74. Permission State

前端维护：

```text
current capabilities cache
```

例如：

```text
canRead
canEdit
canComment
canManage
```

服务器仍然最终鉴权。

---

# Part N: Task Center

## 75. Task Center Module

负责统一展示长期任务：

```text
AI
Import
Export
History Restore
Purge
Other visible async tasks
```

---

## 76. Task Queries

```text
ListUserTasks
GetTask
```

---

## 77. Task Commands

```text
CancelTask
RetryTask
```

仅在目标 Task 支持时可用。

---

## 78. Task Stream

```text
Task Progress
Task Status
```

Stream 断开后：

```text
Query
```

恢复。

---

# Part O: Offline / Sync

## 79. Offline Module

负责：

```text
offline detection
cached Resource
unsynced state
reconnect
local recovery
storage quota
```

---

## 80. Offline Backend 依赖

离线时：

```text
不依赖服务器继续编辑已缓存 Resource
```

联网后依赖：

```text
Session
Permission
Realtime Sync
```

---

## 81. Offline State

前端拥有：

```text
cached Y.Doc
last local state
unsynced marker
storage state
```

Backend 不持有“浏览器是否离线”状态。

---

## 82. Sync State

至少：

```text
Local
Syncing
Synced
Offline
ReadOnly
Error
```

如果系统提供：

```text
Durable
```

可以额外展示。

---

# Part P: Account / Security

## 83. Account Module

负责：

```text
Account Profile
Email
Password
WeChat Binding
Feishu Binding
Current Session
Recent Login
Account Delete
```

---

## 84. Account Commands

```text
ChangeEmail
ChangePassword
LinkWeChat
UnlinkWeChat
LinkFeishu
UnlinkFeishu
RequestAccountDeletion
```

---

## 85. Account Queries

```text
GetCurrentAccount
GetBoundProviders
GetLoginSecurityInfo
GetCurrentSession
ListActiveDeviceSessions
```

---

# Part Q: Trash

## 86. Trash Module

负责：

```text
Trashed Project
Trashed Folder
Trashed Resource
Restore
Permanent Delete
```

---

## 87. Trash Commands

```text
RestoreProject
RestoreFolder
RestoreResource
PurgeProject
PurgeResource
```

---

## 88. Trash Queries

```text
ListTrashedProjects
ListTrashedResources
GetTrashItem
```

---

# Part R: Mobile Companion

## 89. Mobile Companion Module

第一版只依赖：

```text
Resource Read
Comment
Notification
Share Read
Basic Account
```

不要求桌面所有 Contract 都暴露到移动 UI。

---

## 90. Mobile Contract 原则

移动端仍复用：

```text
同一个 Client Contract
```

但只调用自己支持的 Capability。

不建立第二套：

```text
mobile-only backend
```

除非未来确有性能需求。

---

# Part S: Cross-module Rules

## 91. 模块之间禁止直接共享内部状态

例如：

```text
Comment Module
```

不能直接读取：

```text
Editor internal object
```

需要通过：

```text
NodeRef
RelativePosition
Resource Runtime Interface
```

交互。

---

## 92. AI 与 Editor

AI Module：

```text
不能直接操作 Editor DOM
```

Apply 成功后：

```text
后端正式 Resource Change
↓
Realtime
↓
Editor Runtime
```

---

## 93. Notification 与 Router

Notification 点击后：

```text
Target Reference
↓
Navigation Resolver
↓
Route
↓
Feature Module
```

不能让 Notification Service 保存 UI Component Path。

---

## 94. Search 与 Resource Runtime

Search Result：

```text
resourceId / NodeRef
```

进入：

```text
Resource Runtime
```

再由 Editor Adapter 定位。

---

## 95. Comment 与 Document Editor

创建 TextRange Comment：

```text
Editor Selection
↓
NodeRef + RelativePosition
↓
Comment Command
```

Comment Module 不自己读取 DOM Selection。

---

## 96. Permission 与其他 Feature

PermissionChanged：

```text
更新 Capability State
```

随后影响：

```text
Editor
Comment
AI
Asset
History
Toolbar
```

不要求每个模块分别重新解释原始 Permission 数据。

---

## 97. Session 与所有 Feature

SessionReplaced：

```text
Auth Client
↓
Global Session State
↓
Stop Command
Close Realtime
Protect Unsynced Local Content
```

所有 Feature 统一响应。

---

# Part T: Client Application Events

## 98. 前端内部事件

允许前端定义：

```text
CurrentResourceChanged
CurrentPermissionChanged
SessionReplaced
ResourceRuntimeReady
ResourceRuntimeDisposed
NetworkChanged
OfflineStateChanged
```

这些是前端 Application Event。

---

## 99. 前端事件不是后端事件

不能混淆：

```text
Backend Event
```

与：

```text
Frontend Application Event
```

Backend Event 是系统事实。

Frontend Event 是客户端内部协调机制。

---

# Part U: Module Contract Template

## 100. 每个新前端模块必须填写

以后增加 Feature 时，至少定义：

```text
Module Name

Responsibility

Backend Commands

Backend Queries

Backend Events

Backend Streams

Local State

Server State

Offline Behavior

Permission Requirements

Error States

Navigation Targets

Cross-module Dependencies
```

没有这些信息的模块：

```text
不算架构设计完成
```

---

# Part V: Loading / Error / Empty / Offline

## 101. 每个模块必须支持状态

所有异步 Feature 至少明确：

```text
Loading
Ready
Empty
Error
PermissionDenied
Unavailable
```

涉及离线的模块额外：

```text
Offline
Reconnecting
```

---

## 102. 状态语义统一

不能出现：

```text
Search 的 loading
Comment 的 loading
AI 的 loading
```

三套完全不同状态模型。

可以视觉不同。

但语义层必须一致。

---

# Part W: Query / Cache Boundary

## 103. Query Cache

以下适合 Query Cache：

```text
Workspace
Project Tree
Resource Metadata
Permission
Comments
Notifications
Search Result
History Metadata
Task State
```

---

## 104. 不进入普通 Query Cache

以下 Runtime Object：

```text
Y.Doc
EditorView
ProseMirror State
Awareness
WebSocket
Upload Binary
```

不应塞进普通 Server State Cache。

---

# Part X: Command Boundary

## 105. Command 统一要求

所有业务 Command 必须支持：

```text
typed input
requestId
clear error
permission check
idempotency where needed
```

---

## 106. 前端 Command 成功后的更新方式

优先级：

```text
1 Server Response
2 Backend Event
3 Query Invalidation
```

不能靠：

```text
前端猜数据库最终结果
```

---

## 107. Command 与 Event

例如：

```text
RenameResource Command
↓
Success
↓
ResourceRenamed Event
```

其他打开相同 Project 的客户端通过 Event 得到变化。

---

# Part Y: Stream Boundary

## 108. Stream 分类

前端至少区分：

```text
Resource Stream
Account Stream
Task Stream
```

### Resource Stream

```text
Yjs
Awareness
Resource Event
Comment Event
Permission Event
```

### Account Stream

```text
Notification
Session
Account-level events
```

### Task Stream

```text
AI
Import
Export
Long Task Progress
```

---

## 109. Stream 恢复

任何 Stream 必须有：

```text
Reconnect Strategy
```

并且存在：

```text
Query / Sync
```

恢复当前真实状态。

---

# Part Z: UI Modules Checklist

## 110. UI / UX 需要设计的功能模块

以下是 UI / UX 设计必须覆盖的功能域。

本设计不规定外观，只定义能力存在。

```text
1 Auth
2 Workspace Switcher
3 Project Navigation
4 Resource Tree
5 Resource Workspace
6 Document Editor
7 Code Editor
8 Markdown Editor
9 Text Editor
10 Comment
11 Notification Center
12 Search
13 History
14 AI
15 ChangeSet Review
16 Asset Upload / Preview
17 Import
18 Export
19 Permission / Member
20 Share
21 Task Center
22 Offline / Sync State
23 Account / Security
24 Trash
25 Mobile Read
26 Mobile Comment
27 Mobile Notification
28 Anonymous Share Read
```

---

## 111. UI 设计时必须知道的数据

UI / UX 在设计每个模块时，应明确：

```text
这个模块需要哪些 Query
有哪些 Command
有哪些 Realtime Event
哪些状态是 Pending
哪些错误会发生
权限不足时是什么状态
离线时还能做什么
```

否则视觉稿容易设计出：

```text
后端无法保证
或
状态不完整
```

的交互。

---

## 112. 不要求 UI 设计绑定接口名称

UI / UX 设计时不需要写：

```text
POST /api/v1/comments
```

只需要理解：

```text
Create Comment
Reply
Resolve
```

等能力。

最终路径和 Transport 由 Client SDK 层封装。

---

## 113. UI 不决定一致性

例如 UI 可以设计：

```text
一个漂亮的保存状态
```

但它不能自行定义：

```text
“出现绿色图标就代表 Durable”
```

状态语义必须来自系统 Contract。

---

## 114. UI 不决定权限

按钮可以隐藏。

但：

```text
Permission Capability
```

由后端定义。

UI 只负责表达。

---

## 115. UI 不决定离线合并

UI 可以设计：

```text
Offline Banner
Sync Animation
```

但 CRDT Sync 行为由：

```text
Resource Runtime
Realtime Protocol
```

决定。

---

## 116. UI 不决定 Comment Anchor

UI 可以设计：

```text
inline marker
side panel
bubble
```

但 Comment Anchor 必须来自：

```text
NodeRef
RelativePosition
```

---

## 117. UI 不决定 AI Apply

AI UI 可以设计：

```text
Diff Panel
Review Screen
```

但正式 Apply 必须经过：

```text
ChangeSet
Preflight
Backend Operation
```

---

## 118. UI 不直接决定 Deep Link

UI Navigation 使用：

```text
Target Resolver
```

根据稳定业务引用生成实际页面跳转。

---

# Part AA: Test Contract

## 119. 每个 Frontend Module 至少验证

```text
Query success
Query error
Command success
Command rejection
Permission change
Realtime event
Stream reconnect
Session replaced
Offline state
Navigation target
```

---

## 120. Contract Test

前端与后端 CI 必须验证：

```text
Command schema
Query schema
Event schema
Stream schema
Error code
enum
required field
version
```

---

## 121. Module Integration Test

至少测试：

```text
Permission → Editor
Comment → Notification
Search → Resource Runtime
AI → ChangeSet → Resource
Session → Multi-tab
Offline → Reconnect
History → Preview
```

---

# Part AB: 第一版不做

## 122. 第一版不定义

本模块不定义：

```text
视觉 Design System
色彩
字体
Spacing
布局
Sidebar 样式
Toolbar 样式
Mobile Navigation 样式
动画
Icon
具体 UX 流程细节
```

这些由 UI / UX 设计单独完成。

---

## 123. 第一版不做

```text
Public API
Third-party SDK
第三方前端插件 API
Native Mobile 全功能客户端
Frontend Micro-frontend
每个 Feature 独立部署
复杂前端事件总线平台
自研 Query Framework
```

---

# Part AC: 架构硬约束

## 124. 架构硬约束

1. UI / UX 与 Client Contract 必须分离。
2. 前端所有业务模块必须通过统一 Client SDK / Contract 访问后端。
3. 前端 Feature 不得直接访问内部后端服务。
4. Command / Query / Event / Stream 是所有模块统一交互语义。
5. Internal Contract 与 Client Contract 必须分离。
6. 每个前端模块必须明确 Server State 与 Local State。
7. Y.Doc / Editor Runtime 不得塞入普通全局 Query Cache。
8. Permission Capability 必须由后端提供，前端只表达。
9. Realtime Stream 不得成为唯一 Source of Truth。
10. Stream 丢失后必须能 Query / Sync 恢复。
11. Offline / Session / Permission 变化必须作为跨模块系统状态统一处理。
12. Comment、Search、AI、History 都必须通过稳定业务引用跳转到 Resource。
13. Frontend Module 不能直接操作其他模块的内部 Runtime。
14. UI 不得自行定义数据一致性语义。
15. Client Contract 必须 typed、versioned、testable。
16. 新 Feature 必须使用统一 Module Contract Template。
17. 第一版不开放 Public API。
18. 第一版桌面 Web 是完整体验，移动端只使用已支持 Capability。
19. 多 Tab 共用设备 Session，但 Feature Runtime 相互隔离。
20. Frontend Module Contract 遵守 04、05、18 号设计。

---

## 125. 最终模型

```text
                    UI / UX
                      │
                      ▼
                Feature Module
                      │
             ┌────────┼────────┐
             ▼        ▼        ▼
         Local State Server State Runtime State
                      │
                      ▼
                Application Client
                      │
                      ▼
                   Client SDK
                      │
            ┌─────────┼─────────┐
            ▼         ▼         ▼
         Command    Query     Stream
            │         │         │
            └───── Client Contract ─────┐
                                        ▼
                                   Backend
```

跨模块：

```text
Search
→ ResourceRef / NodeRef
→ Resource Runtime

Comment
→ Anchor
→ Resource Runtime

Notification
→ TargetRef
→ Navigation Resolver

AI
→ ChangeSet
→ Backend Apply
→ Realtime
→ Resource Runtime

Permission
→ Capability State
→ All Features
```

最终边界：

> UI / UX 负责体验，Frontend Module 负责功能编排，Client SDK 负责统一通信，Backend 负责权威业务状态；任何前端模块都不能绕过这条链，也不能自己发明第二套接口、权限或状态真相。
