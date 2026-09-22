# Resource Collaboration Design

## 1. 目标

系统中的所有可实时协作内容统一抽象为 `Resource`。

`Resource` 是系统唯一的实时协作边界。

每个 Resource 独立拥有：

- 协作状态
- 实时同步空间
- 在线状态
- 权限上下文
- 持久化状态
- 版本历史

不同 Resource 之间不共享同一个 CRDT 状态。

---

## 2. 核心关系

系统层级固定为：

```text
Workspace / Project
        │
        └── Resource
              │
              └── Resource Content
```

含义：

```text
Workspace / Project
负责组织 Resource

Resource
负责协作边界

Resource Content
负责具体内容结构
```

例如：

```text
Project
├── README.md
├── main.ts
├── design.md
└── config.json
```

这些应该是多个独立 Resource，而不是一个巨大协作文档。

---

## 3. Resource 类型

第一阶段至少支持：

```text
Document
Code
Text / Markdown
```

不同 Resource 可以拥有不同内容模型。

例如：

```text
Document
→ Yjs
→ 富文档结构
→ ProseMirror / Tiptap

Code
→ Yjs
→ Y.Text
→ Code Editor

Markdown / Text
→ Yjs
→ Y.Text
→ Text Editor
```

统一的是协作能力，不要求所有 Resource 使用相同内容结构。

每一种 Resource Type 必须有唯一、明确的内容模型。

禁止同一种 Resource 在运行过程中随机选择不同的 Source of Truth。

---

## 4. 协作功能

用户打开一个 Resource 后，系统必须：

```text
识别 Resource
↓
检查访问权限
↓
加入对应协作空间
↓
加载当前共享状态
↓
同步在线用户
↓
开始实时编辑
```

多个用户可以同时进入同一 Resource。

同一个 Resource 内必须满足：

- 内容修改实时同步
- 支持多人并发修改
- 使用 Yjs 解决 CRDT 合并
- 显示当前在线用户
- 显示其他用户的 Cursor / Selection
- 用户离开后 Presence 自动消失
- 不存在传统“保存”按钮

---

## 5. 协作隔离

Resource A 的任何实时状态不得影响 Resource B。

例如：

```text
A 正在大量编辑 main.ts
```

不能导致：

```text
README.md
design.md
app.ts
```

发生不必要的同步、锁定或重新加载。

服务端必须能够独立管理多个 Resource 的协作活动。

---

## 6. Resource 生命周期与协作运行状态分离

Resource 是长期存在的数据对象。

实时协作环境只在需要时运行。

例如：

```text
Resource 存在
↓
当前无人打开
↓
无需长期占用完整实时协作运行状态
```

有人进入后：

```text
加载协作状态
↓
建立实时 Session
↓
多人协作
```

所有用户离开后，可以根据缓存策略释放运行时资源。

不得因为 Resource 存在，就要求服务端永久维持其完整 Y.Doc 和连接状态。

---

## 7. 统一资源身份

系统级统一使用：

```text
resourceId
```

表示一个 Resource。

协作、权限、历史记录、AI、评论、审计等系统都使用同一个 `resourceId`。

不要为同一个逻辑 Resource 再平行建立：

```text
documentId
fileId
roomId
collaborationId
```

等不同身份体系。

需要定位 Document 内部 Node 时：

```text
NodeRef
=
resourceId
+
nodeId
```

需要定位文本范围时：

```text
resourceId
+
nodeId
+
RelativePosition
```

保持已有 Node Identity 设计不变。

---

## 8. WebSocket 行为

实时通信以 Resource 为路由边界。

客户端进入某个资源时，表达的是：

```text
加入 resourceId 对应的协作空间
```

而不是为不同资源类型分别建立：

```text
joinDocument
joinCode
joinMarkdown
```

协作基础设施不需要理解：

```text
paragraph
heading
table
TypeScript AST
```

这些属于具体 Resource Type。

实时通信至少需要承载两类数据：

```text
Persistent Collaboration State
→ Yjs Update

Temporary Presence State
→ Awareness
```

两者不得混为一种持久化数据。

---

## 9. 权限

每次加入 Resource 协作空间前必须进行权限判断。

至少区分：

```text
read
edit
```

没有编辑权限的用户：

- 可以接收实时内容更新
- 可以查看允许展示的在线状态
- 不得产生能够修改共享 Resource 的有效更新

权限属于 Resource，不属于内部某一个 Block。

更细粒度的权限以后单独扩展，不污染当前协作模型。

---

## 10. 持久化与恢复

每个 Resource 独立持久化。

系统采用：

```text
Hot State
+
Durable Update Journal
+
Checkpoint
+
Compaction
```

保证在以下情况后仍能恢复正确共享状态：

- 服务端重启
- Resource Session 被回收
- 网络中断
- 客户端重新连接
- 某个 Resource 暂时无人在线

实时同步仍以 Yjs Update 为主。

`Durable Update Journal` 是当前状态可靠恢复的主链。

`Checkpoint` 只用于缩短恢复路径和控制长期数据规模，不承担每次编辑的保存职责。

Resource 冷启动时应能够通过：

```text
Latest Verified Checkpoint
+
Checkpoint 之后的 Durable Journal
```

恢复服务端 Y.Doc，再通过 Yjs State Vector 与客户端补齐差异。

持久化、Checkpoint 和 Compaction 不得阻塞实时编辑主路径。

具体存储引擎、批量策略和触发阈值由 Persistence Design 与实现阶段决定。

---

## 11. History

版本历史属于 Resource。

一个 Resource 的历史不能与另一个 Resource 混在一起。

History 应支持后续实现：

- 查看历史状态
- 恢复历史版本
- 比较版本
- 审计修改

Persistence 与 History 可以复用部分底层 Journal / Checkpoint 数据，但两者不是同一个能力：

```text
Persistence
解决当前状态能否可靠恢复

History
解决过去状态能否被查看、比较和恢复
```

但 History 不应重新引入传统的：

```text
每次编辑
→ version++
```

作为实时冲突控制机制。

实时并发仍由 Yjs 负责。

---

## 12. 跨 Resource 操作

跨 Resource 修改不是单个 Yjs Transaction。

例如 AI 同时修改：

```text
main.ts
app.ts
README.md
```

实际上是：

```text
Resource A
+
Resource B
+
Resource C
```

三个独立协作对象。

不得为了实现跨文件修改，把多个 Resource 强行放进同一个 Y.Doc。

未来统一由更高层：

```text
ChangeSet
或
Operation
```

协调。

这一层负责：

- 一次任务涉及哪些 Resource
- 哪些修改成功
- 哪些失败
- 是否需要回滚或重试

具体设计留到跨 Resource 操作模块。

---

## 13. 并发与性能要求

实现时必须原生考虑多个用户、多个 Resource 同时活动。

不允许把整个系统设计成：

```text
所有 Resource
↓
单个全局串行处理队列
↓
逐个执行
```

不同 Resource 应可以并行工作。

同一个 Resource 内由 Yjs 保证并发修改收敛。

网络发送、持久化、Presence 等不应无理由阻塞编辑主路径。

高频事件，例如：

```text
Cursor
Selection
Presence
```

允许合并、节流或丢弃过期中间状态。

正文 Yjs Update 不得因为 Presence 拥堵而丢失。

---

## 14. Resource Type 扩展

以后增加新的：

```text
Diagram
Whiteboard
Config
Notebook
```

等 Resource 时，不应该修改整个协作核心。

新增 Resource Type 主要负责：

- 定义自身内容模型
- 定义编辑方式
- 定义数据验证
- 定义序列化 / 导出方式

底层仍然复用：

```text
Resource Identity
Permission
Realtime Connection
Presence
Persistence
History
```

---

## 15. 必须避免

开发过程中不得出现：

```text
Document 一套协作服务
Code 一套协作服务
Markdown 又一套协作服务
```

不得把：

```text
Workspace / Project
```

直接作为默认 CRDT 协作边界。

不得把：

```text
Block
```

提升为系统级协作 Room。

不得让不同 Resource 共享同一个 Awareness 状态。

不得让 Resource Type 的具体内容结构渗透到通用协作基础设施中。

---

## 16. 验收条件

这一模块完成后，至少能够验证：

```text
两个用户打开同一个 Document
→ 实时共同编辑

两个用户打开同一个 Code Resource
→ 实时共同编辑

一个用户同时打开多个 Resource
→ 各 Resource 独立同步

两个不同 Resource 同时高频修改
→ 互不阻塞

用户进入 / 离开
→ Presence 正确更新

断线重新连接
→ 能恢复正确内容

服务端重启
→ Resource 能从持久化状态恢复

只读用户进入
→ 可以同步但不能修改

新增一种 Resource Type
→ 不需要重写协作核心
```

---

## 17. 架构硬约束

> `Resource` 是系统唯一的实时协作边界。每个 Resource 独立拥有 CRDT 状态、同步空间、Presence、权限上下文、持久化和版本历史；Resource Type 只负责决定内部内容模型，不能重新建立另一套协作基础设施。
