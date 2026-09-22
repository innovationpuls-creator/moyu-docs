# Node Identity / Block ID Design

## 1. 设计结论

文档里的稳定身份统一使用：

```text
nodeId

```

而不是只使用：

```text
blockId

```

原因是实际需要身份的不只有普通 Block。

例如：

```text
paragraph
heading
codeBlock
listItem
tableRow
tableCell
image
callout

```

以后评论、AI、拖拽、表格操作都可能需要定位它们。

因此：

```text
Node
├── nodeId
├── type
├── attrs
└── content

```

其中：

```text
doc
text
mark

```

不需要 `nodeId`。

也就是说：

> 所有需要被独立操作或引用的结构节点都有 `nodeId`，纯文本和文本格式没有。

Tiptap 的 UniqueID 也支持给指定 Node 类型甚至所有非 `doc`、非 `text` Node 分配 ID，这和这里的模型一致。

---

# 2. nodeId 存在哪里

正式身份存储位置：

```text
ProseMirror Node.attrs.nodeId
              ⇅
        y-prosemirror
              ⇅
Y.XmlElement attribute

```

例如 ProseMirror：

```json
{
  "type": "paragraph",
  "attrs": {
    "nodeId": "n_019fd84..."
  }
}

```

进入 Yjs 后，对应节点继续保存同一个属性。

Yjs 的 `Y.XmlFragment` 本身就是 y-prosemirror 映射 ProseMirror 文档的共享结构。

所以：

```text
nodeId 不存 DOM
nodeId 不存 React state
nodeId 不存单独的 Map 映射表
nodeId 不依赖文档位置
nodeId 不依赖 Yjs 内部 Item ID

```

真正的协作数据来源仍然是：

```text
Y.Doc
└── Y.XmlFragment
     └── Node
          └── nodeId

```

---

# 3. nodeId 的核心含义

`nodeId` 表示：

> 一个逻辑文档节点在其生命周期中的身份。

因此它和内容无关。

例如：

```text
n_A
paragraph
"hello"

```

修改成：

```text
n_A
paragraph
"hello world"

```

还是 `n_A`。

从：

```text
paragraph

```

改成：

```text
heading

```

如果用户的操作含义只是“把这个内容块改成标题”，仍然是：

```text
n_A

```

节点内容、样式、位置变化，不自动改变身份。

---

# 4. 身份不变量

整个系统必须保证下面四条规则。

### 4.1 存在性

所有 identity-bearing Node 必须有 `nodeId`。

不能长期存在：

```text
paragraph
nodeId = null

```

---

### 4.2 文档内唯一

同一 Document 内：

```text
nodeId

```

必须唯一。

禁止：

```text
paragraph n_A
heading   n_A

```

---

### 4.3 生命周期不可修改

节点一旦获得：

```text
nodeId = n_A

```

后续不能变成：

```text
nodeId = n_B

```

除非它实际上是一个新节点。

---

### 4.4 ID 永不复用

删除：

```text
n_A

```

以后不能再把 `n_A` 分配给其他节点。

即使内容完全一样也不行。

---

# 5. ID 格式

推荐：

```text
UUIDv7

```

业务表示：

```text
n_019fd84c...

```

例如：

```text
n_019fd84c-f3b2-7...

```

客户端可以离线生成，不需要请求服务器：

```text
Client A → n_A
Client B → n_B

```

碰撞概率可以忽略。

`nodeId` 只表示身份。

不要根据 ID 判断：

```text
文档顺序
父子关系
显示顺序
编辑顺序

```

这些全部由 Document Tree 决定。

---

# 6. 哪些 Node 有 ID

建议第一版直接规定：

```text
doc                 ×

paragraph           ✓
heading             ✓
blockquote          ✓
codeBlock           ✓
image               ✓
callout             ✓

bulletList          ✓
orderedList         ✓
listItem            ✓

table               ✓
tableRow            ✓
tableHeader         ✓
tableCell           ✓

mention             ✓
inlineImage         ✓

text                ×
mark                 ×

```

原则很简单：

> 能被独立选择、引用、移动、删除、评论或者 AI 修改的 Node，都应该有身份。

例如：

```text
table
└── row n_R
     └── cell n_C
          └── paragraph n_P

```

以后 AI 可以明确表达：

```text
修改 n_C 这个单元格

```

而不是：

```text
找到第三张表第二行第四列

```

后者在多人编辑后非常容易失效。

---

# 7. 创建

所有真正的新 Node：

```text
create

```

生成新的 ID。

例如：

```text
insertParagraph()

→ paragraph
   nodeId = n_A

```

生成发生在本地即可。

不需要：

```text
前端请求服务器
↓
服务器生成 ID
↓
返回前端

```

否则每次新增 Block 都增加一次网络依赖。

---

# 8. 普通编辑

下面操作全部保持 ID：

```text
输入文字
删除文字
修改格式
改变 heading level
修改 attrs
改变 code language
调整图片大小
改变 callout 类型

```

例如：

```text
n_A paragraph
↓
修改 type
↓
n_A heading

```

---

# 9. Move

移动必须保持 ID。

例如：

```text
n_A
n_B
n_C

```

移动：

```text
n_C
n_A
n_B

```

依然：

```text
n_C

```

注意 Yjs Shared Type 本身不能在已经插入后直接重新集成到另一个位置。Yjs 官方明确说明 integrated shared type 不能直接移动。

所以底层可能执行：

```text
delete old node
+
insert equivalent node

```

但从业务身份看：

```text
nodeId

```

必须复制过去。

因此要区分：

```text
createNode()
→ new ID

moveNode()
→ keep ID

```

---

# 10. Duplicate

Duplicate 表示创建新的逻辑对象：

```text
n_A
↓ duplicate
n_A
n_B

```

内容可以一样。

身份不能一样。

---

# 11. Split

例如：

```text
n_A
abcdef

```

用户在中间 Enter：

```text
n_A
abc

n_B
def

```

规则：

```text
原节点保留 ID
新节点获得新 ID

```

因此外部原有引用仍然可以继续指向：

```text
n_A

```

---

# 12. Merge

原来：

```text
n_A abc
n_B def

```

合并后：

```text
n_A abcdef

```

规则：

```text
目标节点保留
来源节点死亡

```

即：

```text
n_A → alive
n_B → deleted

```

不能生成：

```text
n_C

```

否则原有引用全部无故失效。

---

# 13. Copy / Paste

普通复制粘贴必须重新生成 ID。

例如复制：

```text
n_A

```

粘贴：

```text
n_A
n_B

```

不能把剪贴板里的 `nodeId` 原样复制。

否则：

```text
同一 Document
出现两个 n_A

```

---

# 14. Drag & Drop

同一文档内部拖动：

```text
move
→ keep ID

```

从其他文档拖入：

```text
copy
→ new ID

```

因此拖拽协议必须知道：

```text
sourceDocumentId

```

不能只根据 HTML 判断。

---

# 15. Cut / Paste

Cut 比普通 Copy 更复杂。

建议支持内部专用 Clipboard metadata：

```text
application/x-document-nodes

```

其中包含：

```text
sourceDocumentId
nodeIds
operation = cut
moveToken

```

如果：

```text
同一个 Document
+
有效 moveToken
+
原节点已经删除

```

可以认为这是 Move：

```text
keep ID

```

否则统一按 Copy：

```text
new ID

```

这样可以同时解决：

```text
Ctrl+X / Ctrl+V
跨文档粘贴
重复粘贴
剪贴板长期保存

```

这些情况。

---

# 16. Import

外部：

```text
HTML
Markdown
DOCX
纯文本

```

默认都没有我们的 Node Identity。

正确流程：

```text
外部内容
↓
Parse
↓
ProseMirror Document
↓
Identity Normalization
↓
生成 nodeId
↓
Schema Validation
↓
写入 Y.Doc

```

不要：

```text
先进入 Y.Doc
↓
所有客户端发现缺少 ID
↓
分别补 ID

```

否则两个客户端可能同时生成：

```text
n_A
n_B

```

---

# 17. 第一次初始化

协作文档初始化必须遵循：

```text
创建 Y.Doc
↓
连接 Provider
↓
等待 initial sync
↓
判断 Document 是否真的为空
↓
为空才创建初始 Document
↓
生成 Node ID
↓
启动 Editor

```

Tiptap 官方明确提醒，UniqueID 与 Collaboration 同时使用时，如果在 Provider 完成同步以前挂载编辑器，可能把本地默认内容永久写进共享文档。

所以：

```text
Editor mounted

```

不能代表：

```text
Document initialized

```

---

# 18. ProseMirror Extension

可以使用：

```text
@tiptap/extension-unique-id

```

但是它只是实现工具。

真正的项目规则应该由自己的：

```text
NodeIdentityExtension

```

包装。

例如：

```text
NodeIdentityExtension
├── ID 类型列表
├── generateNodeId()
├── paste policy
├── split policy
├── merge policy
├── remote transaction policy
├── normalization
└── invariant check

```

底层可以调用 Tiptap UniqueID。

不要把整个身份语义寄托在第三方扩展的默认行为上。

---

# 19. Remote Transaction

远程 Yjs 更新到达客户端时：

```text
remote update

```

客户端不能再次给已有节点生成 ID。

正确逻辑：

```text
Remote:
n_A paragraph
↓
Client B
↓
仍然 n_A

```

Tiptap UniqueID 提供 `filterTransaction`，官方也专门给出了忽略 Collaboration-origin transaction 的用法。

即：

```text
remote transaction
→ accept identity
→ 不执行本地 ID 生成

```

---

# 20. Transaction Intent

结构操作需要明确语义。

建议 Transaction metadata 至少包含：

```text
origin
operation

```

例如：

```text
origin:
  user
  ai
  plugin
  import
  migration
  remote

operation:
  create
  update
  move
  duplicate
  split
  merge
  paste
  delete

```

这样 NodeIdentityExtension 才知道：

```text
该保留 ID
还是
该生成 ID

```

不能仅通过：

```text
“发现一个新 ProseMirror Node”

```

判断。

因为：

```text
Move

```

在底层也可能表现成：

```text
delete + insert

```

---

# 21. Yjs 与 ProseMirror 的职责

职责必须分开：

```text
ProseMirror
负责：
文档结构
编辑操作
Schema
Transaction

NodeIdentity
负责：
逻辑节点身份规则

Yjs
负责：
并发状态
同步
CRDT 合并

WebSocket
负责：
运输 Yjs Update

```

Yjs 不应该决定：

```text
什么时候生成 nodeId

```

这是应用层语义。

---

# 22. Source of Truth

协作期间：

```text
Y.Doc

```

是文档状态来源。

因此：

```text
Y.XmlElement.attrs.nodeId

```

是持久协作身份。

ProseMirror：

```text
Node.attrs.nodeId

```

是当前 Editor 对这份数据的表现。

不要再维护：

```text
Map<position, nodeId>

```

或者：

```text
Map<YjsInternalId, nodeId>

```

这种第二身份系统。

---

# 23. HTML

渲染 HTML 时可以输出：

```html
<p data-node-id="n_A">

```

但：

```text
data-node-id

```

只是序列化结果。

它不是身份来源。

所以：

```text
DOM 被重新创建
React rerender
页面刷新
HTMLElement 被替换

```

都不影响节点身份。

---

# 24. API JSON

对外 JSON：

```json
{
  "type": "paragraph",
  "attrs": {
    "nodeId": "n_A"
  },
  "content": []
}

```

因此：

```text
AI
插件
搜索
评论
审计
导出

```

都可以使用统一 ID。

---

# 25. 外部引用

引用节点时统一使用：

```text
resourceId
+
nodeId

```

不要只保存：

```text
nodeId

```

因为 ID 虽然全局碰撞概率极低，但资源边界本身仍然应该明确。

例如：

```text
NodeRef {
  resourceId
  nodeId
}

```

---

# 26. 文本范围引用

`nodeId` 只负责定位节点。

例如：

```text
paragraph n_A

```

如果还要定位里面某几个字符：

```text
NodeRef
+
Y.RelativePosition

```

例如 Comment：

```text
CommentAnchor
├── resourceId
├── nodeId
├── startRelativePosition
└── endRelativePosition

```

不要长期存：

```text
offset = 37

```

因为其他用户在前面输入以后绝对位置会变化。

---

# 27. 删除

删除节点意味着：

```text
Identity 生命周期结束

```

例如：

```text
n_A → deleted

```

Document 内不需要：

```text
deleted = true

```

但外部系统可能仍然存在：

```text
Comment → n_A
AI Task → n_A
Audit → n_A

```

这些系统必须允许：

```text
target = missing/deleted

```

而不是偷偷让它们指向附近节点。

---

# 28. Undo

如果用户：

```text
删除 n_A
↓
Undo

```

恢复出来的应该还是：

```text
n_A

```

而不是：

```text
n_B

```

因为 Undo 的含义是恢复原节点，不是创建相似的新节点。

这也是为什么 ID 必须进入 Yjs / ProseMirror 内容，而不能在外部临时生成。

---

# 29. Version History

旧版本：

```text
Snapshot 1
n_A

```

当前版本：

```text
n_A

```

两者可以明确知道：

> 这是同一个逻辑节点在不同时间的状态。

这会让后续：

```text
版本 Diff
历史恢复
AI 变化分析
审计

```

简单很多。

---

# 30. Migration

如果旧文档没有 `nodeId`：

```text
Schema v1
↓
Migration
↓
Schema v2

```

由一次 Migration 统一生成。

Migration 必须是受控操作：

```text
锁定 migration
↓
加载完整 Y.Doc
↓
生成所有缺失 ID
↓
验证唯一性
↓
保存
↓
schemaVersion + 1
↓
开放正常协作

```

不能让普通客户端各自补。

---

# 31. Duplicate ID 修复

如果由于 Bug 已经产生：

```text
n_A
n_A

```

不能让所有客户端自动随机修复。

应该：

```text
detect
↓
进入 repair
↓
确定一个节点保留 n_A
↓
其他节点生成新 ID
↓
写入一次 Migration Transaction

```

同时记录：

```text
identityRepair

```

方便审计。

---

# 32. 服务端完整性

这里只靠前端 Extension 还不够。

因为客户端完全可以绕过 Tiptap，直接发送：

```text
Yjs Update

```

修改：

```text
nodeId

```

所以正式服务端至少需要维护：

```text
Node Identity Validator

```

检查：

```text
必须存在
必须唯一
格式合法
Schema 合法

```

以及：

```text
现有 Node ID 不应无理由发生变化

```

---

# 33. 严格验证模式

如果需要防止错误客户端甚至恶意客户端破坏文档：

每个 Room 可以维护：

```text
Authoritative Y.Doc
Validation Y.Doc

```

收到：

```text
incoming update

```

先：

```text
apply → Validation Y.Doc
↓
validate

```

合法：

```text
apply → Authoritative Y.Doc
↓
persist
↓
broadcast

```

非法：

```text
reject
↓
重建 Validation Y.Doc

```

这样非法 CRDT Update 不会先污染正式共享文档。

代价是：

```text
CPU
Memory

```

会更高。

因此它可以作为严格安全模式，而不是所有部署都必须开启。

---

# 34. 普通生产模式

对于只有官方客户端的系统，可以采用：

```text
客户端强约束
+
服务端定期/结构变更检查
+
持久化前检查

```

这样性能更好。

但原则上要知道：

> Yjs 解决的是并发一致性，不负责你的业务身份合法性。

---

# 35. ID Index

为了快速：

```text
nodeId → Node

```

客户端可以建立运行时索引：

```text
NodeIdentityIndex
Map<NodeId, Position/NodeRef>

```

这个 Index：

```text
不是 Source of Truth

```

它只是缓存。

文档变化后增量更新即可。

如果丢失：

```text
重新扫描 Document Tree

```

就可以恢复。

---

# 36. AI 修改

AI 不允许使用：

```text
第 4 段
第 17 个节点
position = 438

```

作为长期目标。

应该：

```text
replaceNode({
  resourceId,
  nodeId
})

```

或者：

```text
replaceRange({
  resourceId,
  nodeId,
  range
})

```

执行前重新解析：

```text
NodeRef
→ 当前 Document 位置

```

这样用户即使在 AI 生成期间移动了 Block，AI 仍然知道自己修改谁。

---

# 37. 并发删除

例如：

```text
A 正在修改 n_A
B 删除 n_A

```

不能因为 A 的修改回来就：

```text
重新创建 n_A

```

删除和编辑的最终状态交给 CRDT 合并。

应用层只遵守：

```text
不存在的 nodeId
不能被偷偷映射到新节点

```

如果 AI 或业务命令执行时目标已经消失：

```text
TARGET_NOT_FOUND

```

停止该操作。

---

# 38. Schema 兼容

不同客户端版本可能认识不同 Node。

例如新版本：

```text
diagram
nodeId = n_D

```

旧客户端不认识 `diagram`。

旧客户端不能：

```text
删除 n_D
转换成 paragraph
重新生成 ID

```

因此 Schema Version 协商必须在进入编辑以前完成。

Identity 不能拿来掩盖 Schema 不兼容问题。

---

# 39. 推荐模块

```text
document/
├── identity/
│   ├── node-id.ts
│   ├── node-identity-extension.ts
│   ├── node-identity-policy.ts
│   ├── node-identity-index.ts
│   ├── normalize-identities.ts
│   ├── validate-identities.ts
│   └── identity-migration.ts
│
├── commands/
│   ├── create-node.ts
│   ├── move-node.ts
│   ├── duplicate-node.ts
│   ├── split-node.ts
│   ├── merge-node.ts
│   └── delete-node.ts
│
└── clipboard/
    ├── serialize.ts
    ├── deserialize.ts
    └── move-token.ts

```

服务端：

```text
collaboration/
├── validation/
│   ├── schema-validator
│   └── identity-validator
│
├── persistence/
└── websocket/

```

---

# 40. 最终规则表

| 操作ID                |               |
| ------------------- | ------------- |
| 创建                  | 新 ID          |
| 输入文字                | 保留            |
| 修改 attrs            | 保留            |
| paragraph → heading | 保留            |
| Move                | 保留            |
| 同文档 Drag Move       | 保留            |
| Duplicate           | 新 ID          |
| Copy / Paste        | 新 ID          |
| 跨文档 Drag            | 新 ID          |
| Split               | 原节点保留，新节点新 ID |
| Merge               | 目标保留，来源死亡     |
| Delete              | ID 死亡         |
| Undo Delete         | 恢复原 ID        |
| Import              | 新 ID          |
| Remote Sync         | 原样接受          |
| Migration           | 仅缺失节点生成       |
| AI 普通修改             | 保留            |
| AI 新建 Node          | 新 ID          |

---

# 41. 最终架构

最终关系应当是：

```text
                       Node Identity Policy
                              │
                   ┌──────────┴──────────┐
                   │                     │
             Document Commands       Clipboard
                   │                     │
                   └──────────┬──────────┘
                              ▼
                       ProseMirror
                     Node.attrs.nodeId
                              │
                         y-prosemirror
                              │
                              ▼
                           Y.Doc
                              │
                     Y.XmlElement attrs
                              │
                         Yjs Update
                              │
                          WebSocket
                              │
                     Collaboration Server
                              │
                   Identity / Schema Check
                              │
                              ▼
                         Persistence

```

这里真正重要的不是：

```text
UUID 放在哪

```

而是整个系统只承认一个身份规则：

> `nodeId` 表示逻辑节点身份。创建新节点才产生新 ID；对现有逻辑节点的编辑、移动、类型调整、撤销恢复都不改变 ID。

Yjs 保证多人最终拿到一致的数据；ProseMirror 管理编辑结构；Node Identity Policy 保证“这个节点到底还是不是原来的那个节点”。

三者职责不能混在一起。