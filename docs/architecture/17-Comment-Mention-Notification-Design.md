# Comment, Mention & Notification Design

## 1. 目标

本设计定义系统中的评论、回复、@Mention、评论锚点、评论线程状态、站内通知、未读状态与通知跳转能力。

本模块解决：

> 用户如何围绕一个 Resource、一个 Node 或一段文本进行讨论，评论如何在正文持续编辑后仍尽可能保持正确定位，@Mention 如何提醒指定用户，通知如何可靠送达、标记未读并跳转到真实目标，同时避免评论系统破坏 Yjs 实时协作、权限边界和 Resource 生命周期。

本设计按可上线产品标准设计。

---

## 2. 第一版产品决策

第一版确定支持：

```text
Comment
├── 整篇 Resource 评论
├── Node 锚定评论
└── 文本范围锚定评论

Thread
├── Reply
├── Resolve
└── Reopen

Delete
└── 显示“此评论已删除”
    保留 Thread 结构

Mention
└── 只支持 @具体用户

Notification
├── 站内通知中心
├── 未读数量
├── 已读
├── 全部已读
└── 点击跳转目标
```

第一版不做：

```text
@all
@everyone
匿名评论
匿名 @Mention
短信通知
移动 Push
评论独立多人 CRDT 编辑
```

---

## 3. 模块定位

Comment / Mention / Notification 属于：

```text
协作沟通层
```

与正文编辑边界明确分离：

```text
Realtime / Yjs
= 协作修改 Resource 正文

Comment
= 围绕 Resource 内容进行讨论

Mention
= 指定这条讨论需要提醒谁

Notification
= 把需要用户知道的事件送到用户
```

---

## 4. Comment 不是 Yjs 正文

评论线程不能作为：

```text
Document Node
Y.Text
Y.Map
```

直接嵌入正文 Y.Doc 作为唯一存储。

Comment 有独立业务生命周期：

```text
Create
Edit
Delete
Reply
Resolve
Reopen
Permission
Audit
Notification
```

因此 Comment 使用独立领域模型。

---

## 5. Comment Source of Truth

Comment / Thread 的权威业务状态存储在：

```text
PostgreSQL
```

Y.Doc 只负责：

```text
Resource Content
```

评论通过稳定 Anchor 引用正文。

---

## 6. Comment Realtime

评论虽然不放入 Y.Doc，但需要实时协作体验。

在线用户应能实时看到：

```text
新评论
新回复
评论编辑
评论删除
Resolve
Reopen
```

这些变化通过：

```text
Event / Stream
```

进入当前 Resource Subscription。

不是 Yjs Update。

---

## 7. Thread

一次评论讨论使用稳定：

```text
threadId
```

一个 Thread 包含：

```text
Anchor
Root Comment
Replies
Status
Participants
```

---

## 8. Comment

每一条具体评论使用稳定：

```text
commentId
```

Comment 至少归属于：

```text
threadId
resourceId
authorUserId
```

删除评论后：

```text
commentId
```

仍然存在，以保持 Thread 结构。

---

## 9. Reply 结构

第一版采用扁平 Thread：

```text
Thread
├── Root Comment
├── Reply
├── Reply
└── Reply
```

Reply 可以引用被回复的 commentId 作为 UI 上下文，但业务 Thread 不形成无限嵌套树。

---

## 10. Anchor 类型

第一版支持三种 Anchor：

```text
ResourceAnchor
NodeAnchor
TextRangeAnchor
```

---

## 11. ResourceAnchor

ResourceAnchor 表示：

> 这条评论针对整个 Resource，而不是正文中的某个具体位置。

例如：

```text
“这份设计整体还缺异常流程。”
```

Anchor：

```text
resourceId
```

即可。

---

## 12. NodeAnchor

NodeAnchor 表示：

> 评论针对一个稳定结构 Node。

使用：

```text
NodeRef
=
resourceId
+
nodeId
```

例如：

```text
针对某个 Heading
某个 Paragraph
某个 Code Block
某个 Table
```

---

## 13. TextRangeAnchor

TextRangeAnchor 表示：

> 评论针对一个 Node 内的一段具体文本。

推荐逻辑：

```text
NodeRef
+
start RelativePosition
+
end RelativePosition
```

其中位置使用：

```text
Y.RelativePosition
```

或等价 Yjs 稳定相对位置。

---

## 14. 为什么不能使用绝对 Offset

禁止把评论永久定位为：

```text
第 5 段
第 20 到 36 个字符
```

因为多人协作后：

```text
前面插入文字
↓
offset 全部变化
```

会让评论错位。

---

## 15. 为什么不能使用 DOM Selector

禁止使用：

```text
DOM path
CSS selector
HTML index
```

作为长期评论 Anchor。

DOM 是编辑器渲染结果，不是业务稳定身份。

---

## 16. Anchor 与 Node Identity

Comment 必须复用：

```text
02-Node-Identity-Design
```

中的 Node Identity。

不能为 Comment 再创建：

```text
commentBlockId
DOM id
editor path id
```

形成第二套身份系统。

---

## 17. TextRange Anchor 内容快照

TextRangeAnchor 可以额外保存：

```text
selectedTextSnapshot
small surrounding context
```

用于：

- UI 展示
- Anchor 诊断
- Detached 后告诉用户原评论针对什么

但它们只是辅助信息。

不能作为主要定位身份。

---

## 18. Anchor Resolve

打开 Resource 时：

```text
Comment Anchor
↓
Resolve against Current Y.Doc
↓
Current Position
```

TextRangeAnchor 可以随着：

```text
前方插入
前方删除
其他用户编辑
```

移动到新的当前位置。

---

## 19. Anchor 状态

Anchor 至少需要表达：

```text
Active
Detached
```

必要时内部还可以区分：

```text
PartiallyResolved
```

但 UI 第一版不必暴露复杂状态。

---

## 20. Detached Anchor

如果目标内容被真正删除：

```text
Node 不存在
或
Text Range 无法再解析
```

Thread 不应被删除。

进入：

```text
Detached
```

UI 显示：

```text
“原评论位置已不存在”
```

Thread 仍然可以继续查看和回复。

---

## 21. Node 删除

一个 Node 被删除：

```text
NodeAnchor
```

变为 Detached。

不能自动把评论：

```text
重新绑定到附近长得相似的段落
```

避免错误关联。

---

## 22. Undo

如果 Node 删除后通过 Undo 恢复：

且按照 Node Identity Design：

```text
恢复原 nodeId
```

则 Comment Anchor 应尽量重新解析到原 Node。

---

## 23. 文本全部删除

如果 TextRange 内文字全部被删除：

系统可以：

```text
保留 NodeAnchor
+
标记原 TextRange 已消失
```

而不是猜测一个新的文本范围。

---

## 24. Anchor 自动修复边界

允许：

```text
Y.RelativePosition 自然重定位
```

不允许：

```text
全文搜索相似文字
↓
自动把评论挂到“最像”的新段落
```

这种行为可能造成语义错误。

---

## 25. Comment Permission

评论读取依赖：

```text
Resource Read Permission
```

登录用户只要能正常读取 Resource：

```text
默认可以查看评论
```

---

## 26. 创建评论权限

可以创建 / 回复评论的角色：

```text
Owner
Manage
Edit
Comment
```

`Read`：

```text
只能查看
```

---

## 27. Anonymous Share

匿名 Share Link 已确定：

```text
可以匿名读取 Resource
不能评论
不能 Reply
不能 @Mention
```

第一版 Anonymous Share 不展示内部 Comment Thread。

Anonymous Viewer：

```text
Read Resource Content = Yes
Read Internal Comment Thread = No
Comment / Mention = No
```

---

## 28. Comment 不提升权限

评论中：

```text
@User B
```

不能让 User B 自动获得 Resource 权限。

Mention：

```text
只是提醒
```

不是：

```text
Invite
Share
Permission Grant
```

---

## 29. Mention 候选用户

第一版 @Mention 候选人应限制为：

```text
当前能够访问该 Resource 的用户
```

至少不能让评论作者通过 Mention UI 枚举：

```text
整个系统所有用户
```

---

## 30. Mention 身份

Mention 在数据层保存：

```text
userId
```

而不是：

```text
@displayName 字符串
```

因为 Display Name 可以变化或重复。

---

## 31. Mention 展示

UI 展示当前：

```text
Display Name
Avatar
```

如果账号已删除：

```text
Deleted User
```

但 Mention 关系仍保持。

---

## 32. Mention 解析

用户在编辑 Comment 时：

```text
选择 @某个用户
```

前端产生结构化 Mention Token。

不能只依赖服务器从纯文本：

```text
"@张三"
```

猜测用户身份。

---

## 33. Comment 内容

Comment Content 使用轻量 Rich Text Comment Schema。

第一版支持：

```text
Bold
Italic
Inline Code
Link
Mention
Line Break
```

评论内容不复用完整 Document Block Tree，也不允许任意 HTML。Mention 必须是结构化 Token。

---

## 34. Comment 内容安全

Comment Rich Text 必须：

```text
sanitize
escape
validate schema
```

禁止：

```text
script
unsafe HTML
dangerous embed
```

---

## 35. Link

评论中的外部链接应：

```text
安全打开
```

并防：

```text
javascript:
data:
unsafe scheme
```

必要时显示外部链接提示。

---

## 36. Comment Edit

用户可以编辑：

```text
自己的未删除 Comment
```

Edit 不产生新的 Comment。

保留：

```text
editedAt
```

用于 UI 显示：

```text
已编辑
```

---

## 37. Comment Edit History

第一版不要求给普通用户展示：

```text
每次评论编辑的完整历史
```

但系统可以为安全 / Audit 保留必要变更记录。

以后如果需要可增加：

```text
View Edit History
```

---

## 38. Delete Comment

用户删除自己的 Comment 后：

```text
Content → Tombstone
```

UI 显示：

```text
“此评论已删除”
```

但保留：

```text
commentId
threadId
reply order
created position
```

---

## 39. 为什么保留 Tombstone

例如：

```text
A: 这里需要改吗？
B: 我同意上一条。
C: 我已经处理。
```

如果 A 被完全删除：

```text
B / C
```

上下文会断裂。

所以删除后保留 Thread 结构。

---

## 40. Deleted Comment 隐私

Tombstone 不应继续把原正文：

```text
返回给普通用户
```

普通 Comment API 只返回：

```text
deleted = true
```

原内容是否进入 Audit / Retention 由安全策略决定。

---

## 41. Root Comment 删除

如果 Thread Root Comment 被删除：

Thread 仍然保留。

显示：

```text
此评论已删除
├── Reply A
└── Reply B
```

---

## 42. 所有评论都删除

如果一个 Thread 中所有 Comment 都被删除：

可以在正常 UI：

```text
隐藏空 Thread
```

但数据仍按 Retention 处理。

不要求即时物理删除。

---

## 43. Resolve

Resolve 表示：

> 当前讨论已经处理完成。

Thread 进入：

```text
Resolved
```

Comment 和 Replies 不删除。

---

## 44. Reopen

已 Resolve 的 Thread 可以：

```text
Reopen
```

重新进入 Active。

---

## 45. Resolve / Reopen 权限

第一版 Resolve / Reopen 权限：

```text
Thread Creator
Edit
Manage
Owner
```

后端仍使用独立：

```text
canResolveCommentThread
canReopenCommentThread
```

Capability，不把它们简单等价为 `canComment`。

---

## 46. Resolved Thread UI

默认编辑视图可以：

```text
弱化 / 折叠 Resolved Thread
```

用户仍可选择：

```text
查看已解决评论
```

---

## 47. Reply

拥有 Comment Capability 的用户可以回复：

```text
Active Thread
```

对于 Resolved Thread：

```text
Reply = rejected
```

Resolved Thread 必须先 Reopen。

必须先执行：

```text
ReopenThread
```

成功后才能继续 Reply。后端必须执行该 Domain Validation，不能只靠 UI 限制。

---

## 48. Thread Participant

Thread Participant 至少包括：

```text
Root Author
Reply Authors
Mentioned Users
```

用于 Notification 计算。

但 Participant：

```text
不代表 Resource Permission
```

---

## 49. Notification 的定位

Notification 是独立模块。

Comment 只是它的一个事件来源。

最终模型：

```text
Comment Event
AI Event
Permission Event
Import / Export Event
...
↓
Notification Service
↓
Recipient Notification
```

---

## 50. Notification Source of Truth

Notification 状态存储在：

```text
PostgreSQL
```

不进入：

```text
Y.Doc
Awareness
Browser-only State
```

---

## 51. Notification 身份

每条用户通知使用稳定：

```text
notificationId
```

归属于：

```text
recipientUserId
```

---

## 52. 第一版通知渠道

本模块第一版只负责：

```text
In-App Notification
```

即站内通知中心。

不做：

```text
SMS
Mobile Push
Comment Email Digest
```

账号安全邮件、验证邮件继续由 Account/Auth 模块负责。

---

## 53. Notification Center

站内通知中心至少支持：

```text
List
Unread
Read
Mark Read
Mark All Read
Cursor Pagination
Click Target
```

---

## 54. Unread 状态

未读状态是：

```text
per user
```

不能写进 Resource。

User A 已读：

```text
不能让 User B 自动变成已读
```

---

## 55. Unread Count

系统提供：

```text
Unread Count
```

用于：

```text
Notification Badge
```

允许短暂最终一致，但必须最终正确收敛。

---

## 56. Mark Read

`Mark Read` 必须：

```text
idempotent
```

重复请求不会产生异常。

---

## 57. Mark All Read

支持：

```text
Mark All Read
```

作用于当前用户。

大型历史通知不应通过逐条循环更新造成数据库压力。

具体实现由本地 AI决定。

---

## 58. 点击通知

点击通知流程：

```text
notification
↓
resolve current target
↓
permission check
↓
open Resource
↓
jump to Thread / Node / Task
```

不能直接信任通知中保存的旧 URL。

---

## 59. Notification Target

Notification Target 使用稳定业务引用。

例如：

```text
Mention
→ resourceId + threadId + commentId

AI Task
→ taskId

Invite
→ invitationId

Export
→ taskId / exportId
```

不把完整前端 URL 当作唯一目标。

---

## 60. Comment Mention Notification

创建 Comment / Reply 时：

如果包含新的：

```text
@User B
```

生成：

```text
Mention Notification
```

---

## 61. Reply Notification

Thread 新增 Reply 时：

可以通知：

```text
Root Author
其他直接参与者
```

但：

```text
作者自己
```

不通知自己。

---

## 62. Mention 优先于 Reply

如果 User B 同时满足：

```text
被 @Mention
+
本来就是 Thread Participant
```

只生成一个高价值通知。

优先类型：

```text
Mention
```

避免重复。

---

## 63. Comment Edit 与 Mention

编辑 Comment 时：

如果新增了一个之前不存在的 Mention：

```text
可以生成新的 Mention Notification
```

但仅修改文字：

```text
不重新通知所有旧 Mention
```

---

## 64. Mention Spam 防护

不能通过不断：

```text
编辑
删除 @
重新加 @
```

无限轰炸某用户。

需要：

```text
rate limit
dedup window
abuse protection
```

或等价机制。

---

## 65. Resolve Notification

第一版 Resolve 可以通知：

```text
Thread Creator
```

如果 Resolve 操作者就是 Thread Creator：

```text
不通知自己
```

普通 Participant 是否收到 Resolve 通知可由 Notification Aggregation 策略控制。

---

## 66. Reopen Notification

Reopen 时可以通知：

```text
Thread Creator
最近参与者
```

但不应把低价值状态变化发送成大量独立提醒。

---

## 67. 通知去重

Notification Service 必须支持：

```text
dedup
```

例如同一个业务动作重复投递 Event：

```text
不能生成两条完全相同通知
```

---

## 68. 通知聚合

短时间内同一 Resource 大量回复可以在 UI 聚合，例如：

```text
3 人回复了你在《Architecture》的评论
```

但聚合是展示层能力。

底层仍需保留足够事实用于：

```text
跳转
已读
诊断
```

---

## 69. Notification Event

Notification 通常通过 Event 驱动：

```text
CommentCreated
CommentMentioned
ThreadResolved
ThreadReopened
AITaskCompleted
ImportCompleted
...
↓
Notification Consumer
```

---

## 70. Event 丢失保护

Notification 不是核心 Source of Truth。

但 Event 丢失不能让通知永久消失。

至少应有：

```text
Reliable Event
+
Idempotent Consumer
```

高价值通知可以增加：

```text
Reconciliation
```

---

## 71. Notification Consumer 重复

Event Bus 可能：

```text
at-least-once
```

重复投递。

Notification Consumer 必须：

```text
idempotent
```

---

## 72. Notification Delivery 失败

站内通知写入失败：

```text
不能回滚 Comment 创建
```

Comment 是主业务。

Notification：

```text
Retry
↓
Dead Letter
↓
Reconcile
```

---

## 73. Comment 创建顺序

创建 Comment：

```text
Validate Permission
↓
Validate Resource
↓
Validate Anchor
↓
Persist Comment / Thread
↓
Publish Event
↓
Realtime Fanout
↓
Notification
```

不能先通知后发现 Comment 实际创建失败。

---

## 74. Comment Transaction

Comment / Thread 本地业务状态和其 Outbox Event：

```text
建议使用同一 PostgreSQL Transaction
```

通过：

```text
Transactional Outbox
```

保证 Event 最终发布。

---

## 75. Realtime Comment Event

在线 Resource Subscriber 可以收到：

```text
CommentThreadCreated
CommentCreated
CommentEdited
CommentDeleted
ThreadResolved
ThreadReopened
```

这些属于：

```text
Resource Event Stream
```

---

## 76. Event 与 Yjs 顺序

不要求：

```text
Yjs Update
+
Comment Event
```

拥有全局严格顺序。

例如用户选中文字后立即评论：

Comment Anchor 已保存：

```text
NodeRef / RelativePosition
```

客户端根据当前 Y.Doc 解析。

---

## 77. Comment Optimistic UI

前端可以：

```text
optimistically show pending comment
```

提高体验。

但正式 Comment：

```text
必须由服务器确认
```

评论不像正文 Yjs 输入那样默认 Local-first Commit。

---

## 78. 创建失败

如果用户失去评论权限：

```text
前端已显示 Pending Comment
↓
服务器拒绝
```

UI 必须恢复并明确提示。

不能把未确认 Comment 当正式内容。

---

## 79. Idempotency

以下 Command 必须幂等：

```text
CreateThread
ReplyComment
EditComment
DeleteComment
ResolveThread
ReopenThread
MarkNotificationRead
MarkAllNotificationsRead
```

网络重试不能产生重复回复。

---

## 80. Comment Race

两个用户同时：

```text
Resolve
Reopen
```

最终状态必须确定。

不要求全局锁。

使用：

```text
PostgreSQL Transaction
version / conditional update
```

或等价方式。

---

## 81. Edit / Delete Race

用户编辑 Comment 的同时另一授权操作删除它。

最终：

```text
Deleted
```

优先于普通内容编辑。

已删除 Comment 不能被旧 Edit 请求复活。

---

## 82. Resource Rename / Move

Resource Rename / Move：

```text
不改变 threadId
不改变 commentId
不改变 Anchor resourceId
```

Comment 自动跟随 Resource。

---

## 83. Resource Trash

Resource 进入 Trash：

```text
Comment 保留
```

默认：

```text
Read-only
```

不允许继续创建新评论。

Restore 后：

```text
Thread
```

恢复正常。

---

## 84. Resource Permanent Delete

Resource Permanent Delete：

```text
Comment / Thread
```

进入受控 Purge。

Retention / Audit 按系统策略执行。

---

## 85. Resource Duplicate

Duplicate Resource 第一版：

```text
不复制 Comment Thread
```

新 Resource 是新的协作上下文。

避免把旧讨论错误复制到新副本。

---

## 86. Cross Workspace Copy

跨 Workspace Copy：

```text
默认不复制评论
```

尤其避免把原 Workspace 的：

```text
用户身份
内部讨论
Mention
```

泄露到目标 Workspace。

---

## 87. History

Comment 不属于 Resource History 的正文状态。

例如：

```text
Resource Restore Version 5
```

不意味着：

```text
Comment 回滚到 Version 5 时的评论集合
```

Comment Timeline 独立存在。

---

## 88. History Preview

History Preview 默认：

```text
不显示当前 Comment Overlay
```

避免把当前讨论错误叠加到过去正文。

以后如果需要：

```text
Historical Comment Context
```

单独设计。

---

## 89. History Restore 后 Anchor

Resource Restore 可能让：

```text
旧 Node
```

重新出现或消失。

Anchor 在 Current Resource 恢复完成后：

```text
重新 Resolve
```

能找到就重新 Active。

找不到就保持 Detached。

---

## 90. Search

普通 Global Search 第一版：

```text
不把 Comment Content 混入 Resource 正文结果
```

以后可以增加：

```text
Comment Search
```

独立 Filter。

---

## 91. AI

AI 可以在用户有权限时：

```text
读取 Comment Thread
总结讨论
根据评论修改 Resource
```

但 Comment 本身属于独立 Source。

AI 修改正文仍然必须：

```text
ChangeSet
```

---

## 92. AI 创建评论

第一版不默认开放：

```text
AI 自动代表用户发布 Comment
```

AI 可以建议文本。

如果未来开放：

```text
必须作为明确 Tool Capability
```

并记录 Actor Chain。

---

## 93. Mention 与 AI

AI 不能因为 Comment 中：

```text
@某用户
```

自动扩大自己的 Resource 读取范围。

Mention 不是授权。

---

## 94. Plugin

Plugin 创建 Comment：

```text
必须同时满足
User Permission
+
Plugin Scope
+
Comment Capability
```

不能直接写 Comment 表。

---

## 95. Notification Generic Contract

虽然第一版重点是评论通知，Notification 模块必须保持通用。

以后可以接入：

```text
Workspace Invite
Permission Changed
AI Task Ready
Import Failed
Export Ready
Share Changed
```

而不重写 Notification Center。

---

## 96. Notification Type Registry

每种 Notification Type 至少定义：

```text
type
recipient rule
target resolver
display payload
dedup rule
security rule
```

避免不同模块随意拼 Notification JSON。

---

## 97. Notification Payload

通知中只保存：

```text
必要显示信息
稳定业务引用
```

不保存大量 Resource 正文。

尤其不应存：

```text
整篇文档
完整评论 Thread
完整 Asset URL
```

---

## 98. Permission Revoked After Notification

User B 被 @Mention 后收到通知。

随后其 Resource 权限被移除。

Notification Center 再展示时：

```text
必须避免泄露当前无权访问的内容
```

可以显示：

```text
“相关内容已不可访问”
```

而不是继续展示敏感 Snippet。

---

## 99. Notification Target Deleted

如果：

```text
Comment Deleted
Resource Deleted
Task Expired
```

通知不必物理消失。

点击时：

```text
target resolver
```

返回：

```text
TargetUnavailable
```

UI 给出明确提示。

---

## 100. Notification Retention

通知不需要永久保存。

可以使用：

```text
Retention
```

自动清理旧通知。

具体时间由产品决定。

安全 Audit 与 Notification Retention 分离。

---

## 101. Comment Retention

Comment 通常随 Resource 长期保存。

删除后的 Tombstone 可以按 Retention：

```text
保留结构
清理原内容
```

最终物理删除与 Resource Permanent Delete / Compliance 联动。

---

## 102. Notification Account Delete

用户 Account 最终删除后：

```text
其个人 Notification
```

可以按账号删除策略清理。

这不影响：

```text
Audit
Resource Comment
```

的必要历史记录。

---

## 103. Deleted User Comment

评论作者 Account 被删除：

Thread 中仍然显示：

```text
Deleted User
```

Comment 不因为 Account 删除自动消失。

---

## 104. Mention Deleted User

已删除账号：

```text
不能继续作为新的 Mention 候选人
```

历史 Mention 可以显示：

```text
Deleted User
```

---

## 105. Notification Center Scope

第一版 Notification Center 是：

```text
Account-level
```

可以显示来自多个：

```text
Workspace
Project
Resource
```

的通知。

不要求用户逐个 Workspace 切换后才能看到。

---

## 106. Notification Filter

第一版可以支持简单：

```text
All
Unread
```

以后再扩展：

```text
Mentions
Comments
Tasks
Invites
```

不必第一版做复杂筛选器。

---

## 107. Notification Order

通知默认按：

```text
createdAt descending
```

展示。

时间相同的内部稳定顺序由实现决定。

不要求跨系统 Event 全局严格顺序。

---

## 108. Cursor Pagination

Notification Center 使用：

```text
Cursor Pagination
```

避免大量历史通知深分页问题。

---

## 109. Unread Count 性能

Unread Count 是高频 Query。

可以：

```text
缓存
计数器
派生状态
```

优化。

但 PostgreSQL 中必须有可重建的真实读状态。

---

## 110. Badge 最终一致

Notification Badge 允许：

```text
短暂延迟
```

例如：

```text
刚读完
Badge 晚 100ms 更新
```

可以接受。

不能为了严格同步 Badge 阻塞 Comment 主流程。

---

## 111. Comment API 边界

Frontend 只通过正式 Contract：

```text
Command
Query
Event / Stream
```

操作 Comment。

不能让前端直接知道数据库表结构。

---

## 112. Command

典型 Command：

```text
CreateResourceComment
CreateNodeComment
CreateTextRangeComment
ReplyComment
EditComment
DeleteComment
ResolveThread
ReopenThread
MarkNotificationRead
MarkAllNotificationsRead
```

---

## 113. Query

典型 Query：

```text
ListResourceThreads
GetThread
ListResolvedThreads
ListNotifications
GetUnreadNotificationCount
ListMentionCandidates
```

---

## 114. Event

典型 Event：

```text
CommentThreadCreated
CommentCreated
CommentEdited
CommentDeleted
CommentMentioned
ThreadResolved
ThreadReopened
NotificationCreated
NotificationRead
```

---

## 115. Stream

Resource 打开期间：

```text
Comment Realtime Update
```

通过 Resource Event Stream 接收。

Notification Center 可以通过：

```text
Account Event Stream
```

实时更新 Badge。

如果 Stream 断开：

```text
重新 Query
```

即可恢复。

---

## 116. Stream 不是 Source of Truth

客户端漏掉：

```text
NotificationCreated
```

或：

```text
CommentEdited
```

后：

```text
重新 Query
```

必须能够恢复当前状态。

不能依赖浏览器永远在线。

---

## 117. Reconnect

客户端 Reconnect 后：

```text
重新获取 Resource Threads
+
Unread Count
```

或使用增量 Cursor 恢复。

具体优化由实现决定。

---

## 118. Rate Limit

Comment 至少限制：

```text
create rate
reply rate
edit rate
mention rate
```

避免：

```text
spam
mention bombing
```

---

## 119. Comment Size

单条 Comment 必须有：

```text
max content size
```

不能允许用户在 Comment 中塞入：

```text
几十 MB 文本
```

具体大小由产品决定。

---

## 120. Mention Count

单条 Comment 中：

```text
@Mention 数量
```

应有合理上限。

即使第一版没有：

```text
@all
```

也不能允许一条评论逐个 @ 数千用户。

---

## 121. Abuse

如果未来公开协作扩大，Comment 模块应能增加：

```text
report
moderation
spam detection
block
```

第一版不要求完整社区治理系统。

---

## 122. Audit

至少审计高价值事件：

```text
Comment Force Delete（如果未来有管理删除）
Thread Resolve / Reopen
Abuse Action
Bulk Comment Operation
```

普通每条评论创建不一定进入长期安全 Audit。

其业务记录本身已经存在。

---

## 123. Observability

至少监控：

```text
comment create rate
reply rate
comment error
anchor resolve failure
detached anchor count
mention count
mention notification count
notification queue lag
notification create failure
unread query latency
realtime comment event lag
notification dedup count
rate limit hit
```

---

## 124. Anchor Health

需要能够知道：

```text
多少 TextRangeAnchor
```

当前无法解析。

如果 Detached 比例异常升高：

可能说明：

```text
Node Identity
RelativePosition
Editor Conversion
History Restore
```

存在问题。

---

## 125. Notification Lag

至少监控：

```text
Source Event Time
→ Notification Created Time
```

之间：

```text
Notification Lag
```

---

## 126. PostgreSQL 约束

PostgreSQL 至少应保证：

```text
thread → resource relation
comment → thread relation
notification → recipient relation
mention → user relation
```

的重要引用一致性。

具体 Schema 由本地 AI 设计。

---

## 127. Comment 多实例

Comment Service 必须支持：

```text
multiple instances
```

不能依赖：

```text
本地内存
```

维护 Thread 权威状态。

---

## 128. Notification 多实例

Notification Consumer 可以多实例并行。

必须：

```text
idempotent
```

同一个 Event 不能生成重复业务通知。

---

## 129. Failure Isolation

Notification Service 故障：

```text
Comment
```

仍然可以创建。

Comment Realtime Event 暂时失败：

```text
Comment 已经可靠存 PostgreSQL
```

客户端重新 Query 后仍能恢复。

---

## 130. PostgreSQL Failure

PostgreSQL 不可写时：

```text
Comment 创建
Reply
Resolve
Notification Read
```

不能伪装成功。

正文 Yjs 是否仍可短暂继续由 Persistence Design 决定。

---

## 131. Resource Session Failure

Realtime Session 崩溃：

```text
Comment 本身不丢
```

因为 Source of Truth 在 PostgreSQL。

重新打开 Resource：

```text
Query Threads
```

即可恢复。

---

## 132. Search Failure

Search 故障：

```text
Comment
Mention
Notification
```

仍正常。

Mention Candidate 不应依赖 Global Search 才能完成基本成员选择。

---

## 133. Presence 与 Comment 分离

Awareness Presence：

```text
谁正在看 / 光标在哪
```

Comment：

```text
持久讨论
```

不能把 Comment 暂存在 Awareness。

---

## 134. Mention 与 Presence 分离

用户不在线：

```text
仍然可以被 @Mention
```

Mention 不依赖：

```text
当前 Presence
```

---

## 135. Frontend Integration

前端需要维护：

```text
Comment Sidebar
Inline Marker
Selected Text Comment UI
Notification Center
Unread Badge
Jump Target
```

但后端返回：

```text
业务状态
稳定引用
```

不返回 DOM 操作指令。

---

## 136. Inline Marker

Document 前端根据：

```text
Anchor
```

解析当前位置并绘制：

```text
comment marker
highlight
```

Marker 是 UI 派生状态。

不写回 Resource 正文。

---

## 137. Anchor 渲染失败

前端无法解析 Anchor 时：

```text
仍显示 Thread
```

放到：

```text
Detached / General Comments
```

区域。

不能直接隐藏掉讨论。

---

## 138. Notification 跳转

点击 Mention Notification：

```text
Open Resource
↓
Wait Resource Ready
↓
Load Comment Threads
↓
Resolve Anchor
↓
Scroll / Focus Thread
```

如果 Anchor Detached：

```text
打开 Resource
+
打开对应 Thread
```

仍然有意义。

---

## 139. Resource 未打开

Notification 不要求：

```text
Resource 已经在本地缓存
```

Target Resolver 使用稳定：

```text
resourceId
threadId
```

打开对应 Resource。

---

## 140. 第一版不做

第一版暂不实现：

```text
@all
@everyone
@role
匿名评论
匿名评论可见
邮件评论 Digest
短信通知
移动 Push
评论附件
评论语音
任意深度嵌套回复
评论投票 / Emoji Reaction
评论独立版本历史 UI
评论全文 Global Search
AI 自动发布 Comment
跨 Workspace 评论复制
History Version 专属评论
```

---

## 141. 核心验收场景

### 场景 1：整篇 Resource 评论

用户创建：

```text
“这份设计整体缺错误恢复说明。”
```

结果：

- 创建 ResourceAnchor Thread
- 其他在线协作者实时看到
- 不依赖某个 Node

---

### 场景 2：Node 评论

用户对某 Heading 评论。

结果：

```text
NodeRef
```

保存。

其他用户在前面新增内容：

```text
nodeId 不变
```

评论仍定位该 Heading。

---

### 场景 3：文本范围评论

用户选择：

```text
“Durable Journal”
```

创建评论。

另一个用户在这段文字前插入内容。

结果：

```text
RelativePosition
```

跟随变化。

评论仍指向原文本范围。

---

### 场景 4：目标 Node 被删除

用户删除被评论的 Paragraph。

结果：

```text
Thread → Detached
```

评论不丢失。

UI 显示：

```text
原评论位置已不存在
```

---

### 场景 5：Undo 恢复 Node

删除 Node 后 Undo。

Node Identity 恢复。

结果：

```text
Anchor
```

可以重新解析到原 Node。

---

### 场景 6：删除 Root Comment

Thread 已有 3 个回复。

Root Author 删除 Root。

结果：

```text
此评论已删除
├── Reply A
├── Reply B
└── Reply C
```

Thread 结构保持。

---

### 场景 7：Resolve

Thread Creator Resolve。

结果：

- Thread 进入 Resolved
- 评论仍可查看
- 默认从 Active Comment 视图弱化 / 折叠

---

### 场景 8：Comment 角色 Resolve 别人的 Thread

普通 Comment 角色尝试 Resolve 别人创建的 Thread。

结果：

```text
Permission Denied
```

Edit / Manage / Owner 或 Thread Creator 可以 Resolve。

---

### 场景 9：@Mention

User A 评论：

```text
“@UserB 请确认这个接口。”
```

结果：

- 保存结构化 userId Mention
- User B 收到一条 Mention Notification
- 点击后跳转 Resource + Thread

---

### 场景 10：Mention 不授权

User B 没有 Resource Access。

结果：

- 不应作为正常 Mention 候选人
- Mention 不会给 User B 自动增加权限

---

### 场景 11：编辑评论新增 Mention

原 Comment 没有 @UserC。

编辑后增加：

```text
@UserC
```

结果：

- User C 收到 Mention Notification
- 原来已经通知过的 User B 不重复收到旧 Mention

---

### 场景 12：自己回复

User A 回复自己的 Thread。

结果：

```text
不生成“你回复了自己”的通知
```

---

### 场景 13：Mention + Participant 重合

User B 已经是 Thread Participant，同时被 @Mention。

结果：

```text
只生成一个 Mention Notification
```

不是两条重复通知。

---

### 场景 14：Notification Read

User B 点击通知。

结果：

- Notification Mark Read
- Unread Count 更新
- 打开 Resource
- 聚焦 Thread

---

### 场景 15：权限撤销

User B 收到 Mention 后被移除 Resource。

结果：

- Notification 不继续泄露 Resource 内容
- 点击显示目标不可访问
- 不恢复权限

---

### 场景 16：匿名 Share

匿名用户打开 Share Link。

结果：

- 可以看 Resource 正文
- 不展示内部 Comment Thread
- 不能 Comment / Reply / Mention

---

### 场景 17：Resource Move

带评论 Resource 移到另一 Folder。

结果：

```text
threadId / commentId / Anchor
```

全部保持。

Notification Target 仍能打开。

---

### 场景 18：Duplicate Resource

复制带大量评论的 Resource。

结果：

```text
新 Resource 不复制旧 Comment Thread
```

---

### 场景 19：History Restore

Resource Restore 到旧 Version。

结果：

- Comment Timeline 不回滚
- Anchor 重新 Resolve
- 找不到的 Anchor 进入 Detached

---

### 场景 20：Notification Service 故障

User A 创建 @Mention Comment。

Notification Worker 暂时故障。

结果：

- Comment 创建成功
- Event 可靠保留
- Notification 后续 Retry
- 不回滚 Comment

---

### 场景 21：Realtime Comment Event 丢失

Client A 没收到：

```text
CommentCreated
```

结果：

重新打开 / Reconnect 后：

```text
Query Threads
```

仍能获得完整状态。

---

### 场景 22：重复 Create 请求

网络超时导致客户端重复发送 Create Comment。

结果：

```text
只产生一个 Comment
```

---

### 场景 23：Account 删除

Comment Author Account 被删除。

结果：

```text
Deleted User
```

仍保留 Comment 结构。

---

### 场景 24：Notification Target 删除

用户点击一条很旧通知。

对应 Resource 已永久删除。

结果：

```text
相关内容已不可用
```

而不是前端报未知错误。

---

## 142. 本地 AI 实现自由度

本设计不规定：

- Comment 表数量
- Anchor 二进制序列化格式
- PostgreSQL Index 细节
- Notification 聚合表结构
- Notification Cache 产品
- Event Bus 产品
- Comment Rich Text Schema 具体库
- Mention UI 组件
- Unread Counter 具体实现
- Rate Limit 数值
- Notification Retention 天数
- Comment Retention 天数

本地 AI 可以根据现有项目技术栈、规模和压测结果选择。

但必须满足本设计的权限、Anchor 稳定性、通知可靠性、Realtime、删除语义和生命周期要求。

---

## 143. 架构硬约束

1. Comment / Thread 不进入 Y.Doc 作为唯一 Source of Truth。
2. Comment / Notification 权威业务状态使用 PostgreSQL。
3. Comment 必须支持 ResourceAnchor、NodeAnchor、TextRangeAnchor。
4. NodeAnchor 必须使用 NodeRef。
5. TextRangeAnchor 必须使用 Y.RelativePosition 或等价稳定位置能力。
6. 不允许 DOM Selector / 绝对 Offset 作为长期 Anchor。
7. Anchor 失效时 Comment 不删除，进入 Detached。
8. 不允许通过文本相似搜索自动错误重绑 Anchor。
9. Comment 删除使用 Tombstone，显示“此评论已删除”，保持 Thread 结构。
10. 第一版 Reply 使用扁平 Thread，不开放无限嵌套。
11. Read 可以查看评论，Comment / Edit / Manage / Owner 可以创建与回复。
12. Resolve / Reopen 使用独立 Capability；第一版允许 Thread Creator + Edit / Manage / Owner。
13. Anonymous Share 不能读取内部 Comment Thread，也不能 Comment / Mention。
14. Mention 只支持具体 userId，不支持 @all / @everyone。
15. Mention 不授予 Resource Permission。
16. Mention 候选不能成为系统用户枚举入口。
17. Notification 是独立通用模块，Comment 只是 Producer。
18. Notification Read State 必须 per-user，不进入 Y.Doc。
19. Notification Target 必须使用稳定业务引用，不依赖旧 URL。
20. 权限撤销后 Notification 不得继续泄露敏感内容。
21. Comment 创建与 Outbox Event 应保证可靠提交。
22. Notification Consumer 必须支持幂等和重复 Event。
23. Notification 故障不能回滚已经成功的 Comment。
24. Resource Trash 保留 Comment，默认 Read-only。
25. Resource Duplicate / Cross Workspace Copy 第一版不复制 Comment。
26. Resource History Restore 不回滚 Comment Timeline。
27. Comment / Notification Stream 不是 Source of Truth，Reconnect 后必须可 Query 恢复。
28. Comment / Notification 必须支持多实例运行。
29. 高并发 Mention / Comment 必须具备 Rate Limit 和 Abuse Protection。
30. Comment / Mention / Notification 遵守 Unified Module Communication Design。

---

## 144. 最终模型

评论：

```text
Resource
   │
   ├── ResourceAnchor
   │
   ├── NodeAnchor
   │      └── NodeRef
   │
   └── TextRangeAnchor
          ├── NodeRef
          ├── Y.RelativePosition Start
          └── Y.RelativePosition End
                 │
                 ▼
               Thread
                 │
                 ├── Root Comment
                 ├── Reply
                 ├── Reply
                 └── Resolve / Reopen
```

实时：

```text
Comment Command
↓
PostgreSQL
↓
Outbox Event
↓
Resource Event Stream
↓
Online Clients
```

通知：

```text
Comment / Mention Event
↓
Notification Service
↓
recipientUserId
↓
Notification Center
↓
Unread / Read
↓
Target Resolver
↓
Resource + Thread
```

系统必须保证：

> 评论永远围绕稳定业务对象存在，而不是依附脆弱 DOM；Mention 只提醒、不授权；通知只负责把事实送到用户，不成为新的权限系统；即使正文移动、用户离线、Stream 丢失或通知 Worker 暂时故障，讨论和通知最终都能恢复到正确状态。
