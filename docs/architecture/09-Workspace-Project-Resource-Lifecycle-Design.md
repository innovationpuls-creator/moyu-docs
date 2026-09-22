# Workspace Project Resource Lifecycle Design

## 1. 目标

本设计定义系统中 Workspace、Project、Folder 和 Resource 的组织关系与完整生命周期。

本模块解决：

> 用户如何创建、组织、移动、复制、删除、恢复和长期管理协作资源，同时保证 Resource 的身份、实时协作、权限、历史和持久化不会因为目录操作而被破坏。

本模块按可上线产品设计，不把 Workspace / Project / Resource 只当作 Demo 中的几张数据库表。

---

## 2. 核心层级

系统组织关系固定为：

```text
Workspace
└── Project
    ├── Folder
    │   ├── Folder
    │   └── Resource
    └── Resource
```

职责：

```text
Workspace
= 顶层协作与管理空间

Project
= 一组相关 Resource 的工作单元

Folder
= Project 内的组织结构

Resource
= 系统唯一实时协作边界
```

`Folder` 不是 Resource。

Folder：

- 不拥有 Y.Doc
- 不建立 Resource Session
- 不拥有独立正文历史
- 不成为 CRDT 协作边界

---

## 3. Workspace

Workspace 至少支持：

- 创建
- 重命名
- 查看
- 成员管理
- Project 管理
- 删除申请
- 删除撤销
- 最终删除

Workspace 是产品级管理空间。

它不直接承载：

```text
Document Content
Y.Doc
Block Tree
```

---

## 4. Project

Project 至少支持：

- 创建
- 重命名
- 查看
- Archive
- Restore from Archive
- Trash
- Restore from Trash
- Permanent Delete
- Folder 管理
- Resource 管理

Project 主要承担：

```text
组织
导航
权限继承来源
批量管理
```

Project 不是实时协作边界。

---

## 5. Folder

第一版正式支持 Folder。

Folder 至少支持：

- 创建
- 重命名
- 移动
- 嵌套
- 删除
- 恢复

Folder 用于：

```text
代码目录
文档分组
资源分类
```

例如：

```text
Project
├── docs
│   ├── architecture
│   └── api
│
├── src
│   ├── frontend
│   └── backend
│
└── README.md
```

Folder 只负责组织，不复制 Resource 的协作能力。

---

## 6. Resource

Resource 至少支持：

- 创建
- 打开
- 重命名
- 移动
- Duplicate
- Trash
- Restore
- Permanent Delete

Resource 创建后：

```text
resourceId
```

保持稳定。

重命名、移动、归档、恢复都不能改变 `resourceId`。

---

## 7. Resource Type

Resource Type 在创建时确定。

例如：

```text
document
code
markdown
text
```

以后还可以增加：

```text
diagram
whiteboard
notebook
config
```

一个 Resource Type 必须对应明确的内容模型。

Resource Type 不应在正常编辑过程中随意改变。

如果用户需要：

```text
Document → Markdown
Code → Document
```

应由：

```text
Convert / Export / Import
```

产生新的受控结果。

不能直接把已有 Resource 的内部协作模型换掉。

---

## 8. Resource Type Registry

新增 Resource Type 时，不应修改所有 Resource 管理逻辑。

系统应通过统一 Resource Type 能力提供：

```text
创建默认内容
打开对应编辑器
校验内容
序列化
历史预览
Diff
Import / Export
```

具体代码结构由本地 AI 设计。

Lifecycle 模块只关心：

```text
这是一个 Resource
```

不理解内部 paragraph、Y.Text 或 AST。

---

## 9. 稳定身份与位置分离

Resource 的身份：

```text
resourceId
```

Resource 的位置：

```text
Workspace
Project
Folder
```

必须分离。

移动：

```text
Project A/docs/design.md
↓
Project A/archive/design.md
```

仍然是同一个 Resource。

因此：

```text
Resource URL
NodeRef
Comment
History
AI Task
Audit
```

都不应长期依赖当前文件路径作为身份。

---

## 10. 名称设计

用户可见名称必须支持：

```text
中文
日文
韩文
拉丁字母
数字
常见符号
其他 Unicode 文本
```

内部不得要求用户：

```text
只输入英文
手动转拼音
手动生成 slug
```

名称是显示与组织信息。

身份由稳定 ID 提供。

---

## 11. 名称标准化

系统应保留用户输入的原始显示名称。

同时建立用于比较和冲突检查的规范化表示。

至少需要正确处理：

- Unicode normalization
- 大小写比较策略
- 前后空白
- 空名称
- 超长名称
- 不可安全显示的控制字符

具体字符规则由产品和目标平台确定。

不能直接用用户显示名称作为数据库主键或 Resource ID。

---

## 12. 同级名称冲突

Project Tree 中同一父 Folder 下：

```text
Resource / Folder
```

不应产生无法区分的同名项。

创建、重命名、移动、恢复时必须检查目标位置的名称冲突。

冲突处理可以：

- 要求用户改名
- 自动生成安全副本名
- 在 Restore / Duplicate 等场景自动追加后缀

具体 UI 由产品实现决定。

系统不能静默覆盖已有 Resource。

---

## 13. Create Resource

创建 Resource 至少需要完成：

```text
确定 Resource Type
↓
生成稳定 resourceId
↓
创建 Resource Metadata
↓
根据 Resource Type 创建初始协作状态
↓
建立权限上下文
↓
进入正常可用状态
```

创建过程必须具备幂等保护。

网络重试不能创建多个意外副本。

---

## 14. 初始内容

不同 Resource Type 可以定义自己的初始内容。

例如：

```text
Document
→ 合法的空 Document

Code
→ 空 Y.Text

Markdown
→ 空文本
```

初始内容必须经过 Resource Type 自己的 Schema 校验。

Lifecycle 模块不能自己拼接某种 Resource 的内部内容。

---

## 15. Rename

Rename 只改变：

```text
用户可见名称
```

不得改变：

```text
resourceId
Y.Doc
History
Permission Identity
NodeRef
Comment Target
```

正在实时协作的 Resource Rename 后：

```text
Resource Session
```

继续存在。

不能因为改名让所有用户重新建立一个新文档。

---

## 16. Move

Move 表示：

```text
同一个 Resource
改变组织位置
```

Move 后必须保留：

- resourceId
- 当前协作状态
- History
- Comment
- Asset Reference
- Node Identity
- Audit Continuity

Move 不复制正文。

---

## 17. Move 不阻塞编辑

Resource Move 属于 Metadata 操作。

正常情况下不能因为：

```text
从 Folder A 移到 Folder B
```

暂停正在进行的 Yjs 协作。

在线编辑继续。

客户端只需要收到 Resource Metadata / Tree 的更新。

---

## 18. Project 内移动

同一个 Project 内：

```text
Folder A
↓
Folder B
```

属于普通 Move。

必须支持并发用户同时操作 Project Tree。

不能通过长时间锁住整个 Project 来实现。

---

## 19. Workspace 内跨 Project 移动

同一个 Workspace 内：

```text
Project A
↓
Project B
```

允许作为正式 Move 功能。

原则：

- resourceId 保持不变
- History 保持
- Realtime Session 不因路径变化而重建
- Permission 重新计算
- Search / Index 更新组织位置
- Audit 记录来源和目标 Project

如果目标 Project 的权限不同，移动完成后必须立即应用新的 Effective Permission。

---

## 20. Move 导致权限变化

Resource 使用继承权限时，跨 Project Move 可能改变谁可以访问。

因此 Move 不能只更新目录位置。

系统必须同步完成：

```text
Resource Location Change
+
Effective Permission Re-evaluation
+
Realtime Permission Refresh
```

如果某个在线用户因为 Move 失去权限：

```text
当前 Subscription 必须失效或降级
```

不能等刷新页面。

---

## 21. 跨 Workspace Move

第一版不提供普通的跨 Workspace Move。

原因是它可能同时涉及：

- Owner
- Permission
- Guest
- Asset Ownership
- Retention
- Audit
- Compliance
- Billing / Quota

第一版采用：

```text
Copy to another Workspace
+
用户明确删除原 Resource
```

以后如果需要真正的跨 Workspace Transfer，应作为独立高风险产品能力设计。

---

## 22. Duplicate

Duplicate 表示创建一个新的 Resource。

因此：

```text
source resourceId
≠
new resourceId
```

Duplicate 复制：

- 当前 Resource 内容
- 必要 Resource Type Metadata

默认不复制：

- Presence
- 当前 Resource Session
- 原 Resource 的权限成员列表
- 原 Resource 的完整 History
- 未完成 Task
- Audit

新 Resource 使用目标位置的权限规则。

---

## 23. Duplicate 内容一致性

Duplicate 必须基于一个明确、可恢复的 Resource 状态。

不能简单读取：

```text
可能已经过期的数据库 JSON
```

复制时应从当前可靠协作状态或其一致持久化表示生成新 Resource。

多人正在编辑源 Resource 时：

```text
Duplicate
```

也必须得到一个确定的副本起点。

具体一致性机制由本地 AI 根据 Persistence / Realtime 设计实现。

---

## 24. Duplicate 与 History

新 Resource 的 History 从 Duplicate 创建时开始。

可以记录：

```text
Created from Resource X
```

用于 Audit 和产品提示。

但默认不克隆源 Resource 全部历史。

避免：

```text
复制一个文件
↓
把几年历史全部复制一遍
```

造成存储和语义混乱。

---

## 25. Duplicate 与 Asset

如果 Resource 内容引用 Asset：

```text
Duplicate
```

默认复制 Asset Reference。

不应直接复制大型二进制文件。

后续 Asset Design 负责：

```text
Reference Count
Ownership
Retention
Cross-Workspace Copy
```

---

## 26. Project Tree 查询

Project 打开时必须能够高效读取：

```text
Folder
Resource
基础 Metadata
```

不能为了显示文件树：

```text
加载每个 Resource 的 Y.Doc
```

Project Tree 是 Metadata 查询。

Resource Content 是独立加载。

---

## 27. 大型 Project

系统必须考虑：

```text
数千
甚至更多
Resource / Folder
```

的 Project。

因此 Tree 至少应支持：

- 分页或分段加载
- Lazy Load
- 按 Folder 查询
- Search
- 增量更新

不能假设每个 Project 永远只有几十个文件。

---

## 28. Tree Realtime

多人同时管理同一个 Project 时：

```text
Create
Rename
Move
Trash
Restore
```

应该能够近实时反映到其他在线用户的 Project Tree。

Project Tree 的实时 Metadata 更新：

```text
不是 Yjs Document Collaboration
```

可以使用统一 Event / Stream 能力。

不需要为了目录树重新建立一个巨大 Y.Doc。

---

## 29. 并发 Rename

两个用户同时 Rename 同一个 Resource。

系统必须产生一个确定的最终名称。

客户端不能永久分叉。

具体并发控制方式由实现选择。

但必须：

- 检查当前 Resource 状态
- 避免静默覆盖其他高风险 Metadata 修改
- 产生一致 Event
- Audit 可追踪

---

## 30. 并发 Move

两个用户同时 Move 同一个 Resource。

系统最终只能存在一个有效位置。

不能出现：

```text
Resource 同时属于 Folder A 和 Folder B
```

Metadata 权威状态必须保持唯一。

具体事务 / optimistic concurrency / command serialization 由本地 AI 选择。

---

## 31. Move 与打开状态

用户正在打开：

```text
Project A/docs/design.md
```

另一用户将其移到：

```text
Project B/archive/design.md
```

当前编辑页面不应突然变成：

```text
Resource Not Found
```

因为：

```text
resourceId
```

没有变化。

UI 更新 Breadcrumb 和 Project Tree 即可。

如果 Move 导致访问权限丢失，则由 Permission 规则处理。

---

## 32. Trash

删除默认进入：

```text
Trash
```

而不是立即物理删除。

第一版 Resource、Folder、Project 都支持 Trash。

Trash 目的：

- 防止误删
- 支持恢复
- 保留 History
- 给未完成后台任务留出清理窗口

---

## 33. Resource Trash

Resource 进入 Trash 后：

- 新用户不能正常打开编辑
- 正常 Realtime Subscription 关闭
- 新正文写入停止
- Persistence 数据继续保留
- History 继续保留
- Comment / Asset Reference 继续保留
- Search 从正常结果中隐藏
- Audit 记录删除操作

Resource 本身仍然存在。

---

## 34. Trash 与在线用户

正在多人编辑 Resource 时，拥有权限的用户执行 Trash。

系统必须：

```text
Resource Lifecycle → Trashed
↓
通知 Resource Session
↓
停止新的共享写入
↓
通知所有在线 Client
↓
关闭正常 Subscription
```

不能让一部分用户继续编辑已经被删除的 Resource。

客户端未同步本地内容不能静默消失，可提供复制 / 导出等恢复方式。

---

## 35. Folder Trash

Folder 进入 Trash 后，其后代：

```text
Folder
Resource
```

在正常 Project Tree 中全部隐藏。

实现上不要求给每个后代逐条改成 Trash 状态。

可以使用：

```text
Ancestor Lifecycle State
```

进行有效状态计算。

避免删除一个大型 Folder 时产生数万条同步写入。

---

## 36. Project Trash

Project 进入 Trash 后：

- 正常导航中隐藏
- 其下 Resource 不允许正常协作
- Project 内现有 Resource Session 按生命周期规则关闭
- Persistence / History 保留
- 可以整体 Restore

不要求立即逐个物理删除 Resource。

---

## 37. Workspace 删除

Workspace 删除属于最高风险操作。

不能作为普通单击删除。

第一版要求：

```text
Delete Request
↓
Pending Deletion
↓
Retention / Grace Period
↓
Final Purge
```

在最终 Purge 前允许 Owner 撤销删除。

具体确认 UI 和时间策略由产品决定。

---

## 38. Restore

Trash 中的：

```text
Resource
Folder
Project
```

都应支持 Restore。

Restore 优先恢复原位置。

如果原位置已经不存在或发生冲突：

- 允许选择新位置
- 或使用安全默认位置
- 或生成不冲突名称

不能覆盖目标已有 Resource。

---

## 39. Restore 后身份不变

Resource 从 Trash 恢复：

```text
resourceId
```

保持不变。

因此：

- History 继续
- Comment 引用继续
- NodeRef 继续
- AI / Audit 关联继续

Restore 不是创建新 Resource。

---

## 40. Restore 与权限

Resource Restore 后重新计算当前 Effective Permission。

不能简单恢复删除前某个过期权限缓存。

如果上层 Project 权限在 Trash 期间已经变化：

```text
Restore 后应用当前权限规则
```

---

## 41. Permanent Delete

Permanent Delete 是最终物理清理流程。

只能在：

```text
Retention Policy
+
Permission
+
Lifecycle State
```

允许时执行。

Permanent Delete 不应该是一个普通同步 HTTP 请求直接删除所有数据。

大型删除进入：

```text
Async Task
```

---

## 42. Permanent Delete 清理范围

最终 Purge 至少需要协调：

```text
Resource Metadata
Persistence Journal
Checkpoint
History
Comment
Search Index
AI Index
Preview Cache
Permission Binding
Audit Retention
Asset Reference
Background Task
```

但：

```text
Audit
Compliance
Backup
```

是否同时物理删除，由各自保留策略决定。

---

## 43. Permanent Delete 顺序

永久删除必须避免：

```text
Metadata 删除成功
但大型存储残留无法追踪
```

也必须避免：

```text
先删除持久化正文
但 Lifecycle 仍显示 Active
```

Purge 应具有明确状态并支持重试。

例如：

```text
Pending Purge
Purging
Purged
Failed
```

具体实现由本地 AI 选择。

---

## 44. 删除幂等

以下操作必须幂等：

```text
Trash
Restore
Permanent Delete
Project Delete
Workspace Delete Request
```

网络重试不能导致：

- 重复删除
- Restore 两次
- 重复创建 Resource
- Purge 状态损坏

---

## 45. Lifecycle State

产品层至少需要表达以下状态：

### Workspace

```text
Active
PendingDeletion
Deleted
```

### Project

```text
Active
Archived
Trashed
Purging
Deleted
```

### Resource

```text
Active
Trashed
Purging
Deleted
```

Folder 可以：

```text
Active
Trashed
Deleted
```

具体数据库表示由实现决定。

---

## 46. Archive

第一版 Project 支持 Archive。

Archive 表示：

```text
不再活跃
但不是删除
```

Archived Project：

- 从默认 Active 列表隐藏
- 仍可访问
- 仍保留 Resource
- 可以恢复为 Active
- 不进入 Trash Retention

Archived Project 第一版为只读状态。

```text
ProjectArchived
↓
Resource Read = allowed by current Permission
Resource Write = rejected
```

Archive 只改变 Project Lifecycle，不改变 Resource identity、History 或持久化内容。恢复为 Active 后，写能力再按当前 Permission 重新计算。

---

## 47. Resource 不需要第一版 Archive

第一版不单独设计：

```text
Archived Resource
```

Resource 如果不常用，可以：

- 留在 Project
- 移动到 Archive Folder
- 由 Project Archive 管理

避免 Lifecycle 状态过多。

---

## 48. Lifecycle 与 Realtime

Realtime Collaboration 必须消费 Resource Lifecycle 变化。

至少：

```text
ResourceTrashed
ResourceRestored
ResourcePurging
ResourcePurged
ProjectTrashed
WorkspacePendingDeletion
```

影响当前 Subscription。

Rename / Move：

```text
不会关闭 Session
```

Trash / Delete：

```text
会影响 Session
```

---

## 49. Lifecycle 与 Persistence

Rename / Move：

```text
不重写 Yjs Content
```

Trash：

```text
保留 Durable State
```

Permanent Delete：

```text
按照 Purge Task 清理
```

Persistence 不根据路径识别 Resource。

统一使用：

```text
resourceId
```

---

## 50. Lifecycle 与 History

Rename / Move：

```text
可以进入 Audit
```

但不需要生成正文版本。

Trash / Restore：

```text
进入 Lifecycle / Audit History
```

Resource Content History 保持连续。

Permanent Delete：

```text
根据 Retention Policy 处理 History
```

---

## 51. Lifecycle 与 Permission

Create / Move / Restore / Project Change 都可能影响：

```text
Effective Permission
```

Lifecycle 操作完成后必须触发统一权限重新计算和缓存失效。

Permission 仍然是最终访问判断来源。

---

## 52. Lifecycle 与 Search

以下操作必须产生搜索索引更新：

```text
Create
Rename
Move
Trash
Restore
Permanent Delete
```

Search 是派生系统。

Search 更新失败不能回滚已经成功的 Resource Metadata 操作。

通过 Event 最终补齐。

---

## 53. Lifecycle 与 AI / Plugin

AI / Plugin 使用 Resource 时必须重新确认：

```text
Resource 仍存在
Resource 仍 Active
当前 Actor 仍有权限
```

长任务不能因为开始时 Resource Active，就在几分钟后向已经 Trash 的 Resource 写入。

---

## 54. Project Delete 与后台任务

Project 进入 Trash / Delete 时：

```text
AI Task
Import
Export
Index
Migration
```

等后台任务需要感知 Lifecycle。

可以：

- Cancel
- Fail
- Pause
- Finish Read-only Cleanup

具体按 Task 类型决定。

不能继续产生新的正常写入。

---

## 55. Event

Lifecycle 模块遵守 Unified Module Communication Design。

至少产生：

```text
WorkspaceCreated
WorkspaceRenamed
WorkspaceDeletionRequested

ProjectCreated
ProjectRenamed
ProjectArchived
ProjectUnarchived
ProjectTrashed
ProjectRestored
ProjectPurged

FolderCreated
FolderRenamed
FolderMoved
FolderTrashed
FolderRestored

ResourceCreated
ResourceRenamed
ResourceMoved
ResourceDuplicated
ResourceTrashed
ResourceRestored
ResourcePurged
```

Event 表示已经发生的事实。

---

## 56. Command

典型 Command：

```text
CreateWorkspace
RenameWorkspace
RequestWorkspaceDeletion

CreateProject
RenameProject
ArchiveProject
UnarchiveProject
TrashProject
RestoreProject
PurgeProject

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
PurgeResource
```

所有改变状态的 Command 必须：

- 鉴权
- 幂等
- 可审计
- 有明确 Error
- 支持 Trace

---

## 57. Query

典型 Query：

```text
ListWorkspaces
ListProjects
GetProjectTree
ListFolderChildren
GetResourceMetadata
GetTrash
GetLifecycleState
```

Project Tree Query 不加载 Resource Content。

---

## 58. 错误模型

至少需要区分：

```text
Not Found
Permission Denied
Name Conflict
Invalid Parent
Invalid Resource Type
Lifecycle Conflict
Target In Trash
Target Deleted
Operation In Progress
Quota Exceeded
```

具体 Error Code 统一遵守系统通信规范。

---

## 59. Invalid Move

必须阻止：

```text
Folder 移动到自己的子 Folder
```

形成循环。

必须阻止：

```text
Resource 移到不存在的 Project
```

或：

```text
移动到 Trashed / Deleted Parent
```

Project Tree 必须始终保持合法树结构。

---

## 60. 并发与锁边界

不能为了 Create / Rename / Move：

```text
锁整个 Workspace
锁整个 Project 很长时间
```

不同 Project、不同 Folder、不同 Resource 的 Metadata 操作应尽可能并发。

只对真正存在竞争的局部对象建立必要一致性控制。

具体 Transaction / Lock / Optimistic Concurrency 由本地 AI 选择。

---

## 61. 大型批量操作

以下操作可能影响大量对象：

```text
删除大型 Project
移动大型 Folder
复制大型 Project
批量 Restore
跨 Project 大批量 Move
```

不应长时间占用同步请求。

应使用：

```text
Async Task
```

并提供：

- Progress
- Cancel（可安全时）
- Retry
- Failed State
- 最终结果

---

## 62. Quota

Lifecycle 模块需要预留 Quota 能力。

例如：

```text
Workspace Resource Count
Storage
Project Count
Large Asset Usage
```

创建 / Duplicate 等操作应能够被 Quota Policy 拒绝。

第一版不必实现复杂计费。

但不能假设资源无限。

---

## 63. Audit

至少审计：

```text
Workspace Delete Request
Project Trash / Restore / Delete
Resource Trash / Restore / Delete
Cross Project Move
Duplicate
Owner / 管理员发起的大型批量操作
```

普通 Rename 是否进入长期安全 Audit 可以由产品策略决定。

---

## 64. 可观测性

至少监控：

```text
workspace count
project count
resource count
folder count
resource create latency
tree query latency
rename failure
move failure
name conflict
trash / restore count
purge task duration
purge failure
large project operation duration
lifecycle event lag
permission refresh latency after move
realtime session close latency after trash
```

---

## 65. 第一版不做

第一版暂不实现：

```text
跨 Workspace 真正 Move
Project Git Branch
Workspace Federation
任意对象硬链接
同一个 Resource 同时出现在多个 Folder
Symbolic Link
复杂文件系统 ACL
Resource Archive State
```

如果需要：

```text
快捷方式 / 收藏 / 引用
```

应另外设计，不把它伪装成 Resource 多父节点。

---

## 66. 核心验收场景

### 场景 1：创建 Project 与 Resource

用户：

```text
Workspace
↓
New Project
↓
New Folder
↓
New Document
```

结果：

- Resource 获得稳定 resourceId
- 能立即进入正常协作
- Project Tree 可看到
- 权限正确

---

### 场景 2：中文名称

创建：

```text
系统架构设计.md
前端设计
数据库方案
```

结果：

- 正常保存和显示
- 不要求英文名
- 不影响 resourceId
- 重命名后引用仍有效

---

### 场景 3：Rename 在线 Resource

多人正在编辑。

另一用户 Rename。

结果：

- 正文编辑不中断
- resourceId 不变
- Breadcrumb / Tree 更新
- History / Comment 不断裂

---

### 场景 4：Project 内 Move

Resource 从：

```text
docs/
```

移动到：

```text
docs/archive/
```

结果：

- 当前编辑继续
- URL / NodeRef 仍指向同一 Resource
- Tree 实时更新

---

### 场景 5：跨 Project Move

Resource 从 Project A 移动到 Project B。

结果：

- resourceId 不变
- History 保留
- Effective Permission 立即重新计算
- 失去权限的在线用户及时被降级或移除

---

### 场景 6：并发 Move

User A 与 User B 同时移动同一 Resource。

结果：

- 最终只有一个有效位置
- Tree 不分叉
- 客户端最终一致

---

### 场景 7：Duplicate

用户复制 Resource。

结果：

```text
新 resourceId
+
复制当前内容
+
新 History
+
目标位置权限
```

源 Resource 不受影响。

---

### 场景 8：多人编辑时 Duplicate

源 Resource 正在高频编辑。

结果：

- Duplicate 得到一个确定的一致状态
- 不读取过期正文副本
- 源 Resource 不暂停

---

### 场景 9：Trash 在线 Resource

Resource 正在多人编辑。

Owner 执行 Trash。

结果：

- Lifecycle 立即变为 Trashed
- 新写入停止
- 在线用户收到删除状态
- 正常 Subscription 关闭
- Durable State / History 保留

---

### 场景 10：Restore Resource

从 Trash Restore。

结果：

- resourceId 不变
- History 保留
- 原引用恢复有效
- 当前权限重新计算

---

### 场景 11：Restore 名称冲突

原位置已有同名 Resource。

结果：

- 不覆盖已有 Resource
- 用户选择位置 / 名称，或系统生成安全名称

---

### 场景 12：Folder Trash

Folder 内有数千 Resource。

结果：

- 不要求同步逐条改写所有后代
- Tree 快速进入 Trashed 语义
- 后台任务和 Session 正确处理

---

### 场景 13：Project Trash

Project 有大量在线 Resource。

结果：

- Project 进入 Trash
- Resource 正常协作停止
- Persistence / History 保留
- 后续可以整体 Restore

---

### 场景 14：Permanent Delete

Retention 已满足。

Owner 发起永久删除。

结果：

- 进入异步 Purge
- 失败可以重试
- 不留无法追踪的半删除状态
- Asset 只清理不再被其他对象引用的数据

---

### 场景 15：大型 Project

Project 有大量 Folder / Resource。

结果：

- Tree 支持 Lazy Load
- 打开 Project 不加载所有 Y.Doc
- Tree Query 不造成巨大内存压力

---

### 场景 16：后台 AI 与 Resource 删除

AI Task 正在生成。

Resource 被 Trash。

结果：

- 最终写入前检测 Lifecycle
- AI 不能写入已 Trash Resource
- Task 得到明确状态

---

### 场景 17：跨 Workspace

用户尝试普通 Move 到另一个 Workspace。

结果：

- 不作为普通 Move 执行
- 提供 Copy / Transfer 产品路径
- 不静默改变 Owner / Permission / Compliance 边界

---

## 67. 本地 AI 实现自由度

本设计不规定：

- 数据库表数量
- Folder 是否使用 adjacency list / materialized path / closure table
- Metadata Transaction 的具体实现
- Event Bus 产品
- Optimistic Lock 还是局部串行
- Project Tree Cache
- Purge Worker
- Unicode normalization 库
- Async Task Worker 数量
- Tree Pagination 具体参数

本地 AI 可以根据现有技术栈和压力测试选择。

但必须满足本设计的产品功能、身份稳定性、并发正确性、故障恢复和性能边界。

---

## 68. 架构硬约束

1. Workspace、Project、Folder、Resource 职责必须分离。
2. Resource 继续作为系统唯一实时协作边界。
3. Folder 只负责组织，不拥有 Y.Doc 或 Resource Session。
4. Resource 的 `resourceId` 与名称、路径、Project 位置分离。
5. Rename / Move 不改变 resourceId。
6. 用户名称必须原生支持 Unicode 和非英语名称。
7. Project Tree Metadata 查询不能加载所有 Resource Content。
8. Resource Type 创建后不随意原地改变。
9. 同 Workspace 跨 Project Move 保留 Resource Identity 和 History。
10. 跨 Project Move 必须重新计算 Effective Permission。
11. 第一版不支持普通跨 Workspace Move。
12. Duplicate 创建新 Resource Identity，不复制 Presence 和完整 History。
13. Duplicate 必须基于一致的当前 Resource 状态。
14. Delete 默认进入 Trash，不立即物理删除。
15. Trash / Restore 保持 Resource Identity。
16. Folder / Project 大型删除不能要求同步逐条处理全部后代。
17. Permanent Delete 使用可重试的受控 Purge 流程。
18. Project Tree 并发修改最终必须形成唯一合法结构。
19. Resource 不能同时存在多个父位置。
20. Tree 不允许循环。
21. Lifecycle 操作必须与 Permission、Realtime、Persistence、History、Search、AI 正确联动。
22. Rename / Move 不得无理由中断当前 Realtime Session。
23. Trash / Delete 必须及时影响当前 Realtime Session。
24. 长时间、大范围 Lifecycle 操作使用 Async Task。
25. 模块通信遵守 Unified Module Communication Design。

---

## 69. 最终模型

```text
Workspace
│
├── Permission / Members
│
└── Project
    │
    ├── Folder
    │   ├── Folder
    │   │   └── Resource
    │   │
    │   └── Resource
    │
    └── Resource
            │
            ├── Realtime Collaboration
            ├── Persistence
            ├── Permission
            ├── History
            ├── Comment
            ├── Asset Reference
            ├── Search
            └── AI / Plugin
```

身份关系：

```text
Workspace / Project / Folder
= 组织位置

resourceId
= Resource 永久逻辑身份
```

Lifecycle：

```text
Create
↓
Active
├── Rename
├── Move
├── Duplicate → New Resource
└── Trash
      ↓
   Restore
      ↓
    Active

Trash
↓
Retention
↓
Purge
↓
Deleted
```

系统必须保证：

> 用户如何整理 Project，不会改变“这个 Resource 到底是谁”；用户如何删除和恢复，也不会绕过已有的实时协作、权限、持久化和历史体系。
