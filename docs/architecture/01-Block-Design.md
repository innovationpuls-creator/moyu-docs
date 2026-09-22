# Block Design

## 1. 目标

Block 是在线文档中的基本内容单元。

它需要同时满足：

- 支持实时多人编辑
- 支持 Block 嵌套
- 支持富文本
- 支持代码、图片、表格等不同内容
- 支持 Block 移动、复制、删除、拆分、合并
- 支持评论、引用、AI 修改等能力定位内容
- 支持以后增加新的 Block 类型
- 不让业务代码直接依赖 Yjs 内部实现

本设计针对：

```text
Resource
└── Document
    └── Block Tree

```

代码文件等其他 Resource 不强制使用 Block。

例如：

```text
Code Resource
└── Y.Text

Document Resource
└── Block Tree

```

---

# 2. Block 的位置

整个系统分三层：

```text
Resource
    │
    └── Collaborative Document
            │
            └── Block Tree

```

Resource 表示系统中的一个资源，例如：

```text
document
markdown
code
config

```

Block 只负责：

> Document 内部的内容结构。

因此不要让 Block 承担：

```text
文件权限
文件路径
文件所有者
WebSocket 连接
在线状态
历史版本
数据库状态

```

这些属于更高层。

---

# 3. 内部模型不是只有 Block

文档内部统一称为：

```text
Node

```

Node 分为四类：

```text
Node
├── Block Node
├── Structure Node
├── Inline Node
└── Text

```

这是整个设计中非常重要的区分。

---

## 3.1 Block Node

用户能够直接看到和操作的内容块。

例如：

```text
paragraph
heading
codeBlock
image
quote
callout
bulletList
orderedList
table

```

例如：

```text
Block
type = paragraph

"Yjs 是一个 CRDT 库"

```

或者：

```text
Block
type = codeBlock

console.log("hello")

```

---

## 3.2 Structure Node

用于组织 Block，但本身不一定作为普通内容块展示。

例如：

```text
bulletList
└── listItem
    └── paragraph

```

表格：

```text
table
└── tableRow
    └── tableCell
        └── paragraph

```

其中：

```text
listItem
tableRow
tableCell

```

主要负责结构。

这样就不需要为了表格、列表不断给 Block 添加特殊字段。

---

## 3.3 Inline Node

存在于 Block 内部的小型内容对象。

例如：

```text
mention
emoji
inlineImage
hardBreak

```

例如：

```text
你好 @Torch

```

其中 `@Torch` 可以是一个 mention Inline Node。

---

## 3.4 Text

普通文本。

例如：

```text
今天学习 Yjs。

```

其中：

```text
加粗
斜体
删除线
链接
inline code

```

不应该成为 Block。

它们属于文本上的 Mark。

因此：

```text
paragraph
└── Text
    ├── bold
    ├── italic
    └── link

```

---

# 4. Block 基础模型

业务层把 Block 视为一种具有稳定身份的 Node：

```ts
interface Block {
  nodeId: NodeId
  type: BlockType
  attrs: Record<string, unknown>
  content?: Node[]
}
```

核心语义统一为：

```text
nodeId
type
attrs
content
```

其中 `nodeId` 表示逻辑节点身份，不是位置、DOM 标识或数据库主键。

在编辑器和协作存储中，不再复制保存另一份身份字段：

```text
业务语义：Node.nodeId
            ⇅
ProseMirror：Node.attrs.nodeId
            ⇅
y-prosemirror
            ⇅
Yjs：对应 Y.XmlElement attribute
```

因此 `nodeId` 只有一个身份含义和一份协作数据来源。

不额外设计：

```text
children
```

因为 `children` 和 `content` 本质上表达同一件事情。

如果同时存在：

```text
content
children
```

以后很容易出现：

```text
paragraph.content
list.children
table.children
```

每个组件使用不同规则。

统一成：

```text
content
```

即可。

---

# 5. Node Identity

文档中的稳定身份统一使用：

```text
nodeId
```

而不是只给普通 Block 设计 `id`。

所有需要被独立操作或引用的 Node 都应该有稳定 `nodeId`，例如：

```text
paragraph
heading
codeBlock
listItem
tableRow
tableCell
image
callout
mention
```

纯：

```text
doc
text
mark
```

不需要 `nodeId`。

推荐 ID 使用：

```text
UUIDv7
```

业务表示例如：

```text
n_019fd84c...
```

客户端可以独立生成，不需要请求服务器。

不要使用：

```text
数组下标
DOM id
文档位置
数据库自增 ID
Yjs clientID
Yjs 内部 Item ID
```

`nodeId` 只表示：

> 一个逻辑文档节点在其生命周期中的身份。

节点内容、类型、格式和位置变化，不自动改变这个身份。

外部系统引用节点时统一使用：

```ts
interface NodeRef {
  resourceId: ResourceId
  nodeId: NodeId
}
```

因此：

```text
文档内部的短期操作
→ 可以在明确 resource 上下文中使用 nodeId

跨模块、持久化、评论、AI、审计等外部引用
→ 使用 NodeRef
```

`Node Identity / Block ID Design` 是节点身份规则的唯一详细定义；本文件只保留 Block 模型需要的摘要，不再维护另一套 Block ID 规则。

---

# 6. Node Identity 生命周期摘要

身份生命周期统一遵循 `Node Identity / Block ID Design`。

Block Design 只保留以下摘要：

| 操作 | 身份规则 |
| --- | --- |
| Create | 新 `nodeId` |
| 普通编辑 / 修改 attrs / 类型调整 | 保留 `nodeId` |
| Move | 保留 `nodeId` |
| Duplicate | 新 `nodeId` |
| Copy / Paste | 新 `nodeId` |
| Split | 原节点保留，新节点生成新 `nodeId` |
| Merge | 目标节点保留，来源节点身份结束 |
| Delete | `nodeId` 生命周期结束 |
| Undo Delete | 恢复原 `nodeId` |
| Remote Sync | 接受远端已有 `nodeId`，不得重新生成 |
| Import | 为新导入的 identity-bearing Node 生成新 `nodeId` |

这里不再单独定义 Block 专属 ID 生命周期。

需要判断：

```text
create
move
duplicate
split
merge
paste
remote
```

等结构操作时，由统一的 Node Identity Policy 决定是保留还是生成 `nodeId`。

---

# 7. type

`type` 表示 Block 的语义。

例如：

```text
paragraph
heading
quote
codeBlock
image
callout
bulletList
orderedList
table

```

不要使用：

```text
div
span
section

```

因为这些属于 HTML 表现，不是文档语义。

Block 模型不能依赖 DOM。

---

# 8. attrs

`attrs` 保存这个 Block 自己的属性。

例如 Heading：

```json
{
  "level": 2
}

```

Image：

```json
{
  "assetId": "asset_123",
  "alt": "architecture diagram",
  "width": 640,
  "align": "center"
}

```

CodeBlock：

```json
{
  "language": "typescript"
}

```

Callout：

```json
{
  "kind": "warning"
}

```

---

# 9. attrs 的限制

attrs 应该只保存：

```text
小
稳定
可序列化
与 Block 本身有关

```

的数据。

不要放：

```text
整张图片
大型二进制文件
编辑器临时状态
当前光标
用户信息
权限
数据库对象
React Component
DOM

```

例如图片不要存：

```text
data:image/png;base64,...

```

而是：

```text
assetId = asset_123

```

文件本体交给 Asset 系统。

---

# 10. content

`content` 表示 Node 的内部内容。

Paragraph：

```text
paragraph
└── text

```

Quote：

```text
quote
├── paragraph
└── paragraph

```

List：

```text
bulletList
├── listItem
│   └── paragraph
│
└── listItem
    └── paragraph

```

Table：

```text
table
├── tableRow
│   ├── tableCell
│   │   └── paragraph
│   └── tableCell
│       └── paragraph
│
└── tableRow

```

因此：

> Block 允许嵌套，但不是任意嵌套。

---

# 11. Schema

每一种 Block 必须注册自己的规则。

例如：

```ts
BlockSpec {
  type
  kind
  allowedContent
  attrs
}

```

概念上：

```text
paragraph
允许：
  inline*

heading
允许：
  inline*

quote
允许：
  block+

bulletList
允许：
  listItem+

listItem
允许：
  block+

table
允许：
  tableRow+

tableRow
允许：
  tableCell+

tableCell
允许：
  block+

```

所以不能出现：

```text
paragraph
└── table

```

也不能出现：

```text
table
└── heading

```

除非 Schema 明确允许。

---

# 12. 推荐初始 Block Schema

第一阶段建议正式支持：

```text
Document
│
├── paragraph
├── heading
├── blockquote
├── codeBlock
├── bulletList
├── orderedList
├── listItem
├── image
├── horizontalRule
├── callout
└── table
    ├── tableRow
    ├── tableHeader
    └── tableCell

```

Inline：

```text
text
mention
hardBreak

```

Marks：

```text
bold
italic
strike
underline
code
link

```

这套已经足够覆盖普通在线文档。

---

# 13. Yjs 中的表示

Document 使用一个：

```text
Y.Doc

```

正文使用：

```ts
ydoc.getXmlFragment("content")

```

整体关系：

```text
Y.Doc
│
└── Y.XmlFragment("content")
     │
     └── Document Tree

```

`Y.XmlFragment` 本身就是用于管理一组 XML 类型子节点的共享结构，适合保存这种树形内容。

例如逻辑上的：

```text
heading
paragraph
bulletList

```

最终会映射成 Yjs 中的树。

普通文本最终由：

```text
Y.XmlText / Y.Text

```

负责同步。

Y.Text 本身支持文本插入、删除和格式属性。

---

# 14. 不直接操作 Yjs Tree

业务代码不要到处出现：

```ts
new Y.XmlElement(...)
new Y.XmlText(...)
fragment.insert(...)
```

统一修改路径：

```text
UI / AI / Plugin
       │
       ▼
Document Command
       │
       ▼
Editor Transaction
(ProseMirror / Tiptap)
       │
       ▼
y-prosemirror
       │
       ▼
Y.Doc
```

> **硬约束：Document Command 是无状态的操作接口，只负责把业务操作转换为 Editor Transaction；不得保存 Document State、维护独立 Block Tree、直接生成网络消息或直接修改 Yjs Shared Type。**

例如业务想添加 Heading：

```text
insertBlock({
    type: "heading",
    attrs: {
        level: 2
    }
})
```

这个 Command 最终必须形成 Editor Transaction，而不是自己维护一份 Block Tree，也不是直接创建 Yjs 节点。

不要：

```text
创建 Y.XmlElement
设置属性
找到位置
插进去
```

业务层应该理解：

```text
Block
Document Command
```

而不是理解：

```text
Y.XmlElement
Y.XmlText
Yjs 内部结构
```

这样业务模型、编辑器结构和协作实现的职责才能保持分离。

---
# 15. Tiptap / ProseMirror

富文本编辑器推荐：

```text
Tiptap
↓
ProseMirror Schema
↓
y-prosemirror
↓
Y.XmlFragment
↓
Yjs

```

Yjs 官方的 ProseMirror binding 会让共享文档继续满足 ProseMirror Schema，因此 Block Schema 可以同时成为编辑器结构约束。

Tiptap Collaboration 同样直接支持把一个 `Y.Doc` 或指定 Yjs fragment 作为协作文档。

因此不要维护两套：

```text
自己的 Block Tree

+

Tiptap Document Tree

```

应该让：

```text
Block Schema
≈
ProseMirror Schema

```

它们描述同一个 Document Tree。

---

# 16. Source of Truth

协作期间：

```text
Y.Doc

```

是实时内容的 Source of Truth。

不要同时维护：

```text
React state
Block JSON
数据库 JSON
Y.Doc

```

四份可修改状态。

否则迟早会出现：

```text
Yjs 是新的

React state 是旧的

数据库又是另一个版本

```

正确关系：

```text
Y.Doc
   │
   ├── Editor View
   │
   ├── JSON Export
   │
   └── Persistence

```

Block JSON 是：

> 读取、导出、API 和调试格式。

不是实时协作状态的另一份独立副本。

---

# 17. JSON 表示

对外 API 可以把文档表示成普通 JSON。

为了与 ProseMirror / Tiptap 的实际节点结构一致，`nodeId` 序列化在 Node 的 `attrs` 中：

```json
{
  "type": "doc",
  "content": [
    {
      "type": "heading",
      "attrs": {
        "nodeId": "n_01",
        "level": 1
      },
      "content": [
        {
          "type": "text",
          "text": "System Architecture"
        }
      ]
    },
    {
      "type": "paragraph",
      "attrs": {
        "nodeId": "n_02"
      },
      "content": [
        {
          "type": "text",
          "text": "The collaboration core uses Yjs."
        }
      ]
    }
  ]
}
```

这里的：

```text
attrs.nodeId
```

就是该逻辑 Node 的 `nodeId`，不是第二套 ID。

这个 JSON 可以用于：

```text
REST API
导出
AI 读取
搜索索引
测试
Debug
Snapshot 展示
```

但客户端之间实时同步不要传整个 JSON。

---

# 18. 实时同步

实时通信应该发送：

```text
Yjs Update

```

而不是：

```json
{
  "action": "updateBlock",
  "nodeId": "...",
  "text": "..."
}

```

也不是：

```text
每次打字
→ 上传整个 Document JSON

```

Yjs Shared Types 本身负责把协作数据的修改同步到其他副本。

所以通信关系是：

```text
用户操作
   ↓
Editor Transaction
   ↓
Y.Doc change
   ↓
Yjs binary update
   ↓
WebSocket
   ↓
其他客户端

```

---

# 19. Block 操作

业务层应该提供统一的 Document Commands。

例如：

```text
insertBlock
deleteBlock
duplicateBlock
moveBlock
replaceBlock
setBlockAttrs
splitBlock
mergeBlock
```

以及：

```text
insertText
deleteText
formatText
```

> **硬约束：Document Command 是无状态的操作接口，只负责把业务操作转换为 Editor Transaction；不得保存 Document State、维护独立 Block Tree、直接生成网络消息或直接修改 Yjs Shared Type。**

因此这些 Command 不是网络协议，也不是另一套文档状态模型。

执行关系统一为：

```text
Document Command
↓
Editor Transaction
↓
y-prosemirror
↓
Y.Doc change
↓
Yjs Update
↓
协作层同步
```

---
# 20. Move 的特殊规则

Yjs Shared Type 插入到 Yjs Document 后不能直接重新插入到另一个位置。官方文档明确说明已经 integrated 的 Shared Type 不能直接移动，需要重新建立相应结构。

所以：

```text
moveBlock()

```

不要直接尝试：

```text
移动某个 Y.XmlElement 对象

```

应该由编辑器层完成：

```text
删除旧位置
+
在新位置插入等价节点

```

但是：

```text
对应 Node 的 `nodeId` 保持不变

```

所以从业务角度仍然是：

```text
移动同一个 Block

```

---

# 21. 并发规则

Block 系统本身不要再实现一套 Conflict Resolver。

Yjs 负责 CRDT 层面的并发合并。

例如：

```text
A 修改 Block 1

B 修改 Block 2

```

可以正常同时进行。

---

两个人编辑同一 Paragraph：

```text
A:
hello

B:
world

```

字符级并发交给 Yjs。

---

两个人同时改变：

```text
heading.level

```

Yjs 最终保证所有客户端得到一致状态。

业务层不要再额外保存：

```text
block.version

```

并自行判断冲突。

否则会同时存在：

```text
CRDT 冲突系统
+
version 冲突系统

```

两套规则会互相干扰。

---

# 22. 删除

普通 Block 删除采用真正删除：

```text
deleteBlock(nodeId)

```

不在 Block 中增加：

```text
deleted = true

```

因为 Yjs 已经需要处理协作删除。

如果业务上需要：

```text
回收站
审计
历史恢复

```

应该由：

```text
Version History
Snapshot
Resource Trash

```

负责。

不要污染 Block Schema。

---

# 23. Cursor 和 Selection

不要保存：

```text
block.cursor
block.users
block.editingUsers

```

光标属于实时 Session，不属于文档内容。

使用：

```text
Awareness

```

保存：

```text
user
cursor
selection
status

```

Yjs Awareness 本身就是独立于 Y.Doc 的临时状态，不会作为文档内容持久化。

---

# 24. Position

不要长期保存：

```text
blockIndex = 13
characterIndex = 42
```

因为其他用户插入内容后，这些绝对位置可能失效。

节点级定位统一使用：

```text
NodeRef {
  resourceId
  nodeId
}
```

如果调用方已经明确处于某个 Document Resource 内部，可以临时只传：

```text
nodeId
```

但一旦引用需要跨模块保存、传递或持久化，就必须恢复为完整 `NodeRef`。

文本内部定位使用：

```text
NodeRef
+
Y.RelativePosition
```

例如：

```text
CommentAnchor
├── target: NodeRef
├── startRelativePosition
└── endRelativePosition
```

`nodeId` 负责说明“是哪一个逻辑节点”。

`Y.RelativePosition` 负责说明“这个节点内部的哪一段文本位置”。

不要长期依赖：

```text
第几个 Block
第几个字符
绝对 position
```

因为这些位置会随着多人协作修改而变化。

---

# 25. Comment

Comment 不应该成为：

```text
Block.attrs.comments
```

推荐：

```text
Comment
├── id
├── target: NodeRef
├── anchor
├── authorId
├── content
└── status
```

其中：

```text
NodeRef
├── resourceId
└── nodeId
```

Anchor 可以引用整个 Node：

```text
target: NodeRef
```

也可以引用 Node 内的一段文本：

```text
target: NodeRef
+
startRelativePosition
+
endRelativePosition
```

这样评论系统和正文系统分离，同时所有外部引用都使用同一套节点身份定义。

---

# 26. Asset

图片、视频、附件统一走：

```text
Asset

```

Block 只保存引用。

例如：

```json
{
  "type": "image",
  "attrs": {
    "assetId": "asset_a81",
    "alt": "architecture",
    "width": 720
  }
}

```

不要保存：

```text
本地路径
临时 signed URL
二进制数据

```

URL 可以由：

```text
assetId
→ Asset Service
→ URL

```

动态获取。

---

# 27. AI 修改

AI 不应该直接修改：

```text
HTML
DOM
数据库正文
Yjs Shared Type
```

AI 修改最终也应该进入：

```text
Document Command
```

AI 对现有内容的长期目标必须使用：

```text
NodeRef {
  resourceId
  nodeId
}
```

例如：

```text
replaceNode({
  target: NodeRef
})

deleteNode({
  target: NodeRef
})

replaceTextRange({
  target: NodeRef,
  range
})
```

如果 AI 要创建新内容，则由对应的 Create Command 创建新的 `nodeId`。

执行路径仍然只有一条：

```text
AI Intent
↓
Document Command
↓
Editor Transaction
↓
y-prosemirror
↓
Y.Doc change
↓
Yjs Update
```

因此：

```text
人类编辑
AI 编辑
插件编辑
自动格式化
```

最终全部进入同一个协作模型。

这样不会存在：

```text
AI 改了一份数据
用户改的是另一份数据
```

---

# 28. Undo / Redo

Undo 不要自己保存：

```text
旧 Block JSON

```

协作编辑使用 Yjs / 编辑器对应的 Undo Manager。

Yjs 的 `UndoManager` 可以限定追踪哪些 transaction origin，因此可以区分不同来源的修改。

例如：

```text
USER_EDIT
AI_EDIT
FORMATTER
REMOTE
SYSTEM

```

这样以后可以决定：

```text
Ctrl + Z

```

到底撤销：

```text
自己的输入
AI 操作
自动格式化

```

中的哪些行为。

---

# 29. Transaction Origin

所有程序生成的修改建议携带来源。

例如：

```text
USER
AI
PLUGIN
IMPORT
MIGRATION
SYSTEM

```

例如：

```text
AI

replace block
↓
Yjs Transaction
origin = AI

```

这样可以用于：

```text
Undo
审计
事件处理
Debug
Telemetry

```

---

# 30. Version

不要在 Block 上设计：

```text
version
revision
updatedAt

```

每输入一个字符都更新：

```text
updatedAt

```

没有实际意义，而且多人编辑时语义混乱。

版本应该属于：

```text
Document

```

而不是：

```text
Block

```

例如：

```text
Document Snapshot

v1
v2
v3

```

Tiptap/Yjs 协作体系本身也以 Yjs update 和 document version 的方式管理协作文档，而不是给每一个节点维护传统版本号。

---

# 31. Schema Version

Document 应该有：

```text
schemaVersion

```

例如：

```text
schemaVersion = 3

```

它表示：

> 这个 Document 使用哪一版 Block Schema。

不要每一个 Block 都写：

```text
schemaVersion

```

---

# 32. Migration

Schema 改变时：

```text
Schema v1
↓
Migration
↓
Schema v2

```

例如：

旧：

```json
{
  "type": "image",
  "attrs": {
    "url": "..."
  }
}

```

新：

```json
{
  "type": "image",
  "attrs": {
    "assetId": "..."
  }
}

```

由 Migration 统一转换。

不要在组件里写：

```ts
if (oldFormat) ...
else if (newFormat) ...

```

否则几年以后每个 Block 都会堆兼容代码。

---

# 33. 客户端 Schema 一致性

同一协作文档中的客户端必须使用兼容 Schema。

连接时应携带：

```text
protocolVersion
schemaVersion

```

如果：

```text
Client A = Schema 5
Client B = Schema 2

```

而 Schema 2 不认识：

```text
diagram

```

就不能让它直接参与编辑。

否则旧客户端可能把未知内容删掉或者重新规范化。

---

# 34. Unknown Block

为了插件和未来扩展，可以提供：

```text
unknownBlock

```

作为只读降级表示。

例如客户端不知道：

```text
mermaidDiagram

```

可以显示：

```text
Unsupported Block

This content requires a newer client.

```

但不能擅自：

```text
删除
转成 paragraph
清空 attrs

```

数据必须继续保留。

---

# 35. Block Registry

所有 Block 类型统一注册。

例如：

```text
BlockRegistry

paragraph
heading
blockquote
codeBlock
image
callout
table
...

```

每一种 Block 定义：

```text
type
kind
schema
attrs
editor extension
renderer
serializer
commands

```

不要：

```text
if type === paragraph
if type === heading
if type === image

```

散落在整个项目里。

---

# 36. 推荐模块结构

```text
collaboration/
├── document/
│   ├── schema/
│   │   ├── document.ts
│   │   ├── block.ts
│   │   ├── inline.ts
│   │   └── marks.ts
│   │
│   ├── blocks/
│   │   ├── paragraph/
│   │   ├── heading/
│   │   ├── code-block/
│   │   ├── image/
│   │   ├── list/
│   │   ├── table/
│   │   └── callout/
│   │
│   ├── commands/
│   │   ├── insert-block.ts
│   │   ├── delete-block.ts
│   │   ├── move-block.ts
│   │   ├── split-block.ts
│   │   └── merge-block.ts
│   │
│   ├── identity/
│   │   ├── node-id.ts
│   │   ├── node-ref.ts
│   │   ├── node-identity-policy.ts
│   │   ├── node-identity-index.ts
│   │   ├── normalize-identities.ts
│   │   └── validate-identities.ts
│   │
│   ├── migration/
│   │
│   └── serialization/
│
├── yjs/
│   ├── document.ts
│   ├── provider.ts
│   ├── awareness.ts
│   ├── persistence.ts
│   └── undo.ts
│
└── editor/
    ├── tiptap/
    └── adapters/

```

最重要的是：

```text
document/

```

定义“文档是什么”。

```text
yjs/

```

定义“怎么协作”。

不要反过来让：

```text
Yjs

```

决定整个业务模型。

---

# 37. 最终模型

整个系统最终可以收敛成：

```text
Resource
│
├── Document Resource
│      │
│      └── Y.Doc
│           │
│           └── content: Y.XmlFragment
│                 │
│                 └── Document Node Tree
│                      │
│                      ├── Block Node
│                      │    ├── nodeId
│                      │    ├── type
│                      │    ├── attrs
│                      │    └── content
│                      │
│                      ├── Structure Node
│                      │    └── nodeId（需要独立定位时）
│                      │
│                      ├── Inline Node
│                      │    └── nodeId（需要独立定位时）
│                      │
│                      └── Text + Marks
│                           └── 无 nodeId
│
├── Code Resource
│      └── Y.Text
│
└── Other Resource
```

节点身份：

```text
Node Identity
├── nodeId
│    └── 一个逻辑 Node 的稳定身份
│
└── NodeRef
     ├── resourceId
     └── nodeId
```

其中 `nodeId` 用于 Document 内识别逻辑 Node；`NodeRef` 用于评论、AI、搜索、审计等跨模块引用。

协作状态独立：

```text
Awareness
├── user
├── cursor
├── selection
└── presence
```

业务扩展独立：

```text
Comment
Asset
Permission
History
Version
AI
Search
```

它们通过：

```text
NodeRef
+
必要时的 Y.RelativePosition
```

引用 Document，而不是把外部业务状态塞进 Block。

---

# 38. 最终约束

以下规则作为 Block 系统的基础约束：

1. `Block` 是文档语义，不是 DOM。
2. `Block` 是 `Node` 的一种，不是所有东西都是 Block。
3. 所有需要被独立操作或引用的 Node 使用稳定 `nodeId`；纯 `doc`、`text`、`mark` 不使用 `nodeId`。
4. `nodeId` 表示逻辑节点身份；实际协作存储映射到 `ProseMirror Node.attrs.nodeId` 和对应的 Yjs Node attribute，不维护第二身份系统。
5. 跨模块、持久化和外部引用统一使用 `NodeRef { resourceId, nodeId }`。
6. Node Identity 的创建、Move、Duplicate、Split、Merge、Paste、Remote 等生命周期规则只由 `Node Identity / Block ID Design` 定义，本文件不维护另一套 Block ID 规则。
7. 不同时设计 `content` 和 `children`。
8. Block 可以嵌套，但必须由 Schema 限制。
9. 富文本正文使用 `Y.XmlFragment`。
10. 实时文本修改交给 Yjs，不自己实现字符冲突算法。
11. Block JSON 不是协作状态的第二份 Source of Truth。
12. 光标和在线状态使用 Awareness，不进入 Block。
13. 评论等文本范围使用 `NodeRef + Y.RelativePosition`，不使用绝对字符下标。
14. 图片等文件只保存 Asset 引用。
15. AI、插件和用户修改最终都进入统一 Document Command。
16. Document Command 是无状态操作接口，只把业务操作转换为 Editor Transaction；不得保存 Document State、维护独立 Block Tree、直接生成网络消息或直接修改 Yjs Shared Type。
17. Version 属于 Document，不属于 Block。
18. Schema Version 属于 Document。
19. 新 Block 必须通过 Block Registry 注册。
20. 业务模块不直接操作 Y.XmlElement。
21. Tiptap / ProseMirror Schema 与 Block Schema 保持同一个结构定义。
22. Resource 是系统统一抽象，Block 只是 Document Resource 的内部模型。
23. Yjs 是协作内核，不是业务领域模型。
