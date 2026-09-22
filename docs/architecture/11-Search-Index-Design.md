# Search & Index Design

## 1. 目标

本设计定义系统中的统一搜索与索引能力。

本模块解决：

> 用户如何在 Workspace / Project / Resource 范围内快速找到内容，同时保证搜索结果权限正确、索引可恢复、实时协作不被阻塞，并能够支持中文、英文以及其他语言内容。

本模块按可上线产品设计，不把 Search 当成简单的数据库 `LIKE` 查询。

---

## 2. 核心定位

Search 是：

```text
Derived System
```

不是 Source of Truth。

真正的权威数据仍然来自：

```text
Resource Metadata
Resource Content
Permission
Asset Metadata
History
```

Search Index 可以：

- 延迟
- 重建
- 删除
- 重新生成

但不能成为：

```text
正文唯一来源
权限唯一来源
Resource Lifecycle 唯一来源
```

---

## 3. 第一版产品能力

第一版至少支持：

```text
Workspace 全局搜索
Project 内搜索
Folder 范围搜索
Resource 名称搜索
Resource 正文全文搜索
按 Resource Type 过滤
按时间过滤
按成员 / 作者过滤
最近内容搜索
高亮命中
结果排序
权限过滤
搜索历史
搜索建议
```

可选增强：

```text
语义搜索
向量检索
OCR 文本搜索
音视频转写搜索
历史版本搜索
Comment 搜索
```

第一版应为这些能力预留扩展边界。

---

## 4. 搜索范围

Search 至少支持以下 Scope：

```text
Workspace
Project
Folder
Resource Type
Current Resource
```

例如：

```text
搜索整个 Workspace

只搜索 Project A

只搜索 docs/architecture

只搜索 code Resource

只搜索当前 Document
```

---

## 5. 当前 Resource 内查找

当前 Resource 内：

```text
Ctrl + F
Find in Document
Find in Code
```

不应依赖全局 Search Index。

应优先使用：

```text
当前 Editor / Local Resource State
```

原因：

- 当前内容最实时
- 不受索引延迟影响
- 不需要跨服务请求
- 不产生不必要索引压力

因此：

```text
Current Resource Find
≠
Global Search
```

---

## 6. Global Search

跨 Resource 的搜索进入统一 Search Service。

Global Search 查询：

```text
Workspace
Project
Folder
Resource Metadata
Resource Content
```

使用派生索引。

允许存在极短的索引延迟。

但不能因为 Search Index 暂时落后而影响正文编辑。

---

## 7. 索引对象

第一版至少索引：

```text
Resource Metadata
Resource Content
```

其中 Metadata 包括：

```text
resourceId
resourceType
name
projectId
folder path / parent
createdAt
updatedAt
lifecycle state
```

正文索引由 Resource Type Adapter 提供。

---

## 8. Document Resource Index

Document Resource 的索引内容至少包括：

```text
标题
Paragraph Text
Heading Text
Code Block Text
Quote Text
Callout Text
Table Text
List Text
```

不需要把整个 ProseMirror / Yjs 内部结构原样塞进 Search Index。

Search 使用：

```text
可搜索文本表示
+
必要结构 Metadata
```

---

## 9. Node 定位

Document 搜索结果需要能够定位到具体内容位置。

优先返回：

```text
NodeRef
=
resourceId
+
nodeId
```

必要时加：

```text
Relative Position
```

不能长期使用：

```text
第 5 段
字符 offset 328
DOM selector
```

作为跨模块定位。

---

## 10. Code / Text / Markdown Index

Code、Text、Markdown 至少索引：

```text
文件名
正文文本
语言 / 类型
必要 Metadata
```

Code Search 后续可以增强：

```text
symbol
function
class
import
reference
```

但第一版不要求建立完整 Language Server Index。

---

## 11. Asset Metadata Index

Asset 第一版至少可以索引：

```text
display name
file type
MIME
asset metadata
associated Resource
```

可选增强：

```text
OCR text
PDF extracted text
audio transcript
video transcript
```

这些派生内容失败不能影响原 Asset 可用性。

---

## 12. Comment Search

Comment Search 可以作为第一版可选能力。

如果启用，需要：

```text
comment content
author
resourceId
createdAt
status
```

Comment 搜索必须遵守：

```text
Resource Permission
+
Comment Permission
```

不能因为 Search Index 中存在 Comment 就绕过访问控制。

---

## 13. History Search

第一版默认：

```text
不把全部历史版本正文加入普通搜索结果
```

普通 Global Search 优先搜索：

```text
Current Resource State
```

历史版本搜索以后作为独立高级功能。

否则会导致：

- 结果大量重复
- 用户分不清当前 / 历史
- Index 成本急剧增长

---

## 14. Index Document

Search Index 中每条可搜索记录必须带稳定身份。

推荐逻辑身份：

```text
resourceId
```

Document Node 级细粒度记录可以使用：

```text
resourceId + nodeId
```

不能使用：

```text
Search Engine 自增 ID
```

作为业务永久身份。

---

## 15. 搜索结果

搜索结果至少需要表达：

```text
resourceId
resourceType
name
project / folder location
match snippet
match type
updatedAt
target reference
```

Document 内容结果：

```text
target
→ NodeRef
```

Resource 名称结果：

```text
target
→ ResourceRef
```

---

## 16. Search Result 与权限

Search 不能返回：

```text
用户当前无权访问的 Resource
```

包括：

- 标题
- Snippet
- 文件名
- 内容摘要
- Asset Preview
- 历史信息

权限过滤必须是 Search 的核心功能，而不是 UI 端二次隐藏。

---

## 17. 权限检查策略

Search 可以使用：

```text
Index-time Permission Metadata
+
Query-time Permission Validation
```

组合优化。

但高风险场景下：

> Query-time 的当前有效权限必须能够阻止过期索引泄露结果。

不能依赖：

```text
“索引里的 permission 以后会同步”
```

作为唯一安全边界。

---

## 18. 权限变化

当以下事件发生：

```text
PermissionChanged
MemberRemoved
ShareRevoked
ProjectMoved
ResourceMoved
ResourceTrashed
```

Search 必须及时更新或失效相关权限索引。

在索引尚未更新期间：

```text
Query-time Permission
```

仍必须保证不能泄露结果。

---

## 19. Lifecycle

Search 必须消费：

```text
ResourceCreated
ResourceRenamed
ResourceMoved
ResourceTrashed
ResourceRestored
ResourcePurged
ProjectArchived
ProjectUnarchived
ProjectTrashed
ProjectRestored
ProjectPurged
```

`Trashed / Purged` 对象不得进入普通 Search Result；Trash 搜索如果产品需要，应作为独立 Scope。

Archived Project 中的 Resource 默认不进入普通 Global Search Result。Index 必须保留 Lifecycle Metadata，并通过显式 `Archived Filter / Scope` 才返回 Archived 内容。

---

## 20. Resource Rename / Move

Rename：

```text
更新名称索引
```

Move：

```text
更新 Project / Folder / Path Metadata
```

不能因为移动 Resource：

```text
重新索引整份正文
```

除非实现确实需要。

Metadata 更新与 Content Index 应尽量解耦。

---

## 21. 实时协作与索引

用户每输入一个字符：

```text
不能同步触发一次完整重建索引
```

Search Index 采用：

```text
Event-driven
+
Debounce
+
Coalescing
```

或等价策略。

目标：

```text
实时编辑高频
↓
合并为合理的 Index Update
```

避免索引系统反向拖慢 Yjs 编辑。

---

## 22. Index Freshness

Global Search 允许：

```text
短暂最终一致
```

不要求：

```text
用户输入一个字符
↓
1ms 后整个 Workspace Global Search 必须立即搜到
```

但索引延迟必须可控、可监控。

架构阶段不写死固定毫秒值。

具体目标由：

```text
真实用户体验
部署环境
压测
```

确定。

---

## 23. Search Freshness 与 UX

如果索引仍在更新：

```text
用户不需要理解底层 Journal / Index Queue
```

UI 可以保持简单。

对于当前正在编辑的 Resource：

```text
Current Resource Find
```

始终读取本地最新状态。

这样用户不会因为 Global Search 的极短延迟觉得内容“消失”。

---

## 24. Indexing Pipeline

统一 Indexing Pipeline：

```text
Source Change
↓
Event
↓
Index Task
↓
Load Current Source
↓
Permission / Lifecycle Check
↓
Resource Type Extraction
↓
Normalize
↓
Index Write
↓
Search Ready
```

Index Worker 不能自己成为业务 Source of Truth。

---

## 25. Current State Indexing

当 Resource 短时间内产生多个变化：

```text
Update A
Update B
Update C
```

Index Worker 不需要保证：

```text
A
B
C
```

每一个中间状态都进入最终 Search Index。

只要：

```text
最终 Current State
```

正确即可。

这允许：

```text
Coalesce
Skip stale task
Reindex latest state
```

降低成本。

---

## 26. Stale Task

如果：

```text
Index Task v10
```

执行时 Resource 已经到了更新状态：

```text
v15
```

系统应能够：

- 跳过过期任务
- 或直接索引最新状态
- 或保证 v15 后续覆盖 v10

不能让旧 Index Task 最终覆盖新 Index。

具体 version / cursor 机制由本地 AI 实现。

---

## 27. Index Cursor

Search 可以维护自己的：

```text
Index Cursor
```

表示：

```text
已经处理到哪个 Source State
```

这个 Cursor：

```text
不是 Yjs Conflict Version
不是 Resource Version
不是 Permission Version
```

只用于索引新鲜度和任务防乱序。

---

## 28. 初次创建

Resource 创建时：

```text
ResourceCreated
↓
Index Metadata
↓
Index Initial Content
```

Index 失败：

```text
不能回滚 Resource 创建
```

而应进入：

```text
Retry / Failed Task
```

Search 恢复后补齐。

---

## 29. Reindex

系统必须支持：

```text
Single Resource Reindex
Project Reindex
Workspace Reindex
Full Rebuild
```

用于：

- Search Schema 升级
- Analyzer 改变
- Index 损坏
- Bug 修复
- Search Engine 迁移
- 新字段上线

---

## 30. Rebuild 不阻塞生产查询

Index Rebuild 应支持：

```text
Build New Index
↓
Catch Up Changes
↓
Validate
↓
Switch Alias / Active Index
```

或等价无停机方案。

不能：

```text
删掉当前 Index
↓
重建数小时
↓
期间 Search 全部不可用
```

---

## 31. Index Schema Version

Search Schema 必须版本化。

例如：

```text
searchSchemaVersion
```

Schema 变化时：

```text
旧 Index
↓
新 Index Build
↓
Validation
↓
Switch
```

不要在已有大型 Index 上进行不可恢复的在线破坏性修改。

---

## 32. Multilingual

搜索必须原生考虑非英语用户。

至少支持：

```text
中文
英文
日文
韩文
Unicode 文本
```

不能只按：

```text
空格分词
```

作为唯一策略。

中文搜索需要适合中文的：

```text
tokenization / analyzer
```

正式 Search Engine 使用 `OpenSearch 3.x`。Analyzer 通过 Search Adapter 配置为 Unicode / CJK 兼容方案；Analyzer 可以通过 Reindex 演进，但不得由本地 AI 替换 Search Engine。

---

## 33. 中文搜索体验

至少应支持：

```text
完整词
部分词
标题
正文
常见中英文混合
```

例如：

```text
实时协作
Yjs 协作
Resource 设计
```

不能因为中英文混排导致完全搜不到。

---

## 34. Case / Unicode Normalization

索引和查询需要统一处理：

```text
Unicode normalization
大小写
全角 / 半角
常见标点
前后空白
```

但不能破坏用户原始显示文本。

Search Normalize 与 Display Text 分离。

---

## 35. Exact Search

搜索需要支持明确的：

```text
Exact Match
```

场景。

例如：

```text
resource name
file name
exact phrase
```

Exact Match 应与普通 Full-text Match 区分。

---

## 36. Prefix Search

名称搜索建议支持：

```text
prefix
```

例如输入：

```text
arch
```

可以匹配：

```text
architecture.md
```

用于快速导航。

Prefix Search 不应要求复杂全文分词。

---

## 37. Fuzzy Search

可以支持适度 Fuzzy Search。

例如：

```text
拼写错误
少量字符错误
```

但 Fuzzy 不能无限放宽。

否则：

- 结果噪音过大
- 查询成本过高

具体阈值由用户体验测试决定。

---

## 38. Pinyin

中文产品可以后续支持：

```text
拼音搜索
```

例如：

```text
jiagou
→ 架构
```

但第一版不是强制要求。

架构上不要写死不支持。

---

## 39. Ranking

结果排序至少综合：

```text
Exact Name Match
Title Match
Heading Match
Body Match
Recent Activity
Resource Type
Scope Proximity
```

例如：

```text
Resource 名称完全匹配
```

通常应高于：

```text
正文中偶然出现一次
```

具体权重由数据和用户测试调优。

---

## 40. Ranking 不影响权限

Ranking 只能改变：

```text
允许结果的顺序
```

不能：

```text
因为 relevance 高
↓
绕过 Permission
```

权限过滤必须先成立。

---

## 41. Semantic Search

第一版可以把 Semantic Search 设计为可插拔能力。

结构：

```text
Keyword Index
+
Vector Index
↓
Hybrid Search
```

但：

> Keyword / Metadata Search 必须能够独立工作。

不能让向量服务故障导致基础搜索全部不可用。

---

## 42. Embedding

如果启用 Semantic Search：

```text
Embedding
```

属于派生数据。

Embedding 失败：

```text
不能影响 Resource
不能影响 Keyword Search
```

可以异步重试。

---

## 43. Vector Index 权限

Vector Search 与 Keyword Search 使用同样的权限约束。

不能：

```text
Keyword Search 安全
Vector Search 返回无权内容
```

Semantic Search 不得绕过 Permission。

---

## 44. Chunking

Document / 大型文本做 Embedding 时可以 Chunk。

Chunk 必须保留：

```text
resourceId
nodeId / source reference
chunk identity
```

搜索结果必须能够重新定位真实 Resource 内容。

Chunk 本身不是新的业务 Resource。

---

## 45. Chunk 更新

Resource 修改后：

```text
不要求整个 Resource 全部重新 Embedding
```

如果 Resource Type 和实现支持，可以增量更新受影响 Chunk。

具体优化由本地 AI 决定。

---

## 46. AI 与 Search

AI / RAG 可以使用 Search：

```text
Keyword Search
Semantic Search
Hybrid Search
```

作为检索来源。

但 AI 查询必须带：

```text
当前 Actor Permission
当前 Scope
```

AI 不能以后台身份搜索整个 Workspace 所有内容。

---

## 47. RAG 与 Search Index

Search Index 可以作为 RAG 的一个来源。

但：

```text
Search Index
≠
AI Knowledge Base 的唯一真相
```

AI 需要：

```text
Source Reference
resourceId
nodeId
```

才能在生成结果时绑定真实来源。

---

## 48. Search Suggestion

搜索输入框可以提供：

```text
Recent Search
Recent Resource
Matching Resource Name
Matching Project
```

建议功能不需要暴露完整正文内容。

Suggestion 也必须经过 Permission。

---

## 49. Recent Items

Recent Items 可以由：

```text
User Activity
```

单独产生。

不要求通过全文搜索计算。

Search UI 可以混合：

```text
Recent
Suggested
Search Results
```

但后端职责分开。

---

## 50. Search History

用户搜索历史可以保存：

```text
query
scope
time
```

用于：

- 快速重搜
- 产品体验
- 搜索建议

敏感 Workspace 可以允许：

```text
Disable Search History
```

以后扩展。

---

## 51. Search History Privacy

Search History 属于用户私有行为数据。

不能默认：

```text
共享给 Workspace 其他成员
```

Analytics 若使用必须做独立隐私设计。

---

## 52. Highlight

全文搜索结果应返回：

```text
snippet
highlight
```

但：

```text
Snippet 只能来自用户有权读取的内容
```

Highlight 是展示派生数据。

搜索引擎内部高亮格式不应泄漏成业务永久协议。

---

## 53. Long Document

大型 Resource 不应作为一个无限大的 Search Document。

可以：

```text
按 Node
按 Section
按 Chunk
```

建立索引。

具体粒度由 Resource Type Adapter 决定。

但结果仍然归属同一个：

```text
resourceId
```

---

## 54. Search Adapter

每种 Resource Type 提供 Search Adapter。

负责：

```text
Extract Searchable Text
Extract Metadata
Produce Target Reference
Optional Chunking
```

例如：

```text
Document Adapter
Code Adapter
Markdown Adapter
Future Diagram Adapter
```

Search Service 不直接理解 ProseMirror Node Schema。

---

## 55. Asset OCR / Transcript

OCR / Transcript 属于异步派生能力。

流程：

```text
Asset Ready
↓
OCR / Transcript Task
↓
Derived Text
↓
Index
```

失败时：

```text
Asset 仍然 Ready
基础 Metadata Search 仍然正常
```

---

## 56. Search Event Sources

Search 至少消费：

```text
ResourceCreated
ResourceRenamed
ResourceMoved
ResourceTrashed
ResourceRestored
ResourcePurged
ResourceContentChanged
PermissionChanged
MemberRemoved
AssetReady
AssetDeleted
HistoryRestored
```

具体 Event 名称遵守 Unified Module Communication Design。

---

## 57. ResourceContentChanged

Realtime Yjs 每个字符更新不应直接产生一个全局业务 Event。

应由 Resource / Persistence / Index Bridge 形成合理粒度的：

```text
ResourceContentChanged
```

或等价索引触发信号。

具体 Debounce / Coalescing 由实现决定。

---

## 58. Event Reliability

Search 属于派生系统。

Index Event 丢失不能永久造成 Resource 无法搜索。

必须有至少一种补偿：

```text
Reliable Event
Periodic Reconciliation
Reindex
Backfill
```

推荐：

```text
Event-driven
+
Reconciliation
```

---

## 59. Reconciliation

系统应能够发现：

```text
Source 存在
但 Index 缺失

Source 更新
但 Index 过旧

Source 已删除
但 Index 仍存在
```

并自动修复。

不能假设 Event Pipeline 永远 100% 不出错。

---

## 60. Failed Index Task

无法处理的 Index Task：

```text
不能无限重试
不能静默丢弃
```

进入：

```text
Failed Task / Dead Letter
```

可：

- 诊断
- 重放
- 单 Resource Reindex

---

## 61. Search Engine 故障

Search Engine 暂时不可用时：

```text
Realtime Editing
Persistence
Permission
Resource Lifecycle
```

继续工作。

Search UI：

```text
明确提示搜索暂不可用
```

索引任务积压后可以恢复补齐。

Search 故障不能拖垮核心编辑链。

---

## 62. Search Engine 更换

Resource / AI / Plugin 不应依赖 Search Engine 私有字段。

业务层使用统一 Search Contract。

未来：

```text
Engine A
↓
Engine B
```

可以通过 Rebuild / Migration 切换。

---

## 63. 多实例

Search API、Index Worker 都必须支持多实例。

不能依赖：

```text
单机内存队列
单实例 Cron
本地唯一状态
```

保证全局正确性。

---

## 64. Index Queue

Index Pipeline 需要：

```text
Backpressure
```

高峰期不能无限占用内存。

允许：

```text
Coalesce
Batch
Delay
Retry
Skip Stale Task
```

正文实时编辑优先级高于 Search Freshness。

---

## 65. 大规模 Reindex

Full Reindex 不能把线上 Search / Database 打满。

需要支持：

```text
Rate Limit
Batch
Worker Concurrency
Pause
Resume
Progress
```

并作为：

```text
Async Task
```

运行。

---

## 66. Query Limit

Search Query 必须限制：

```text
page size
max result window
query length
filter count
fuzzy complexity
semantic candidate count
```

防止恶意或异常 Query 消耗过多资源。

---

## 67. Pagination

普通 Search 使用：

```text
Cursor-based Pagination
```

或等价稳定分页方案。

不建议依赖超深：

```text
offset = 500000
```

查询。

具体实现取决于 Search Engine。

---

## 68. Facet / Filter

第一版建议支持：

```text
Resource Type
Project
Folder
Modified Time
Creator / Member
```

等过滤。

Facet 结果同样必须受 Permission 约束。

不能：

```text
Facet 显示“你无权访问的 300 个私密文件”
```

泄露存在性。

---

## 69. Deleted Data

Resource Deleted 后：

```text
Search Index
```

必须最终删除。

在 Event 尚未消费的短暂窗口里：

```text
Query-time Lifecycle / Permission
```

仍应避免返回已删除对象。

---

## 70. Trash Search

第一版普通 Search：

```text
默认不搜索 Trash
```

Trash 页面可以有自己的搜索 Scope。

这样避免：

```text
删除的文件
```

混入正常工作结果。

---

## 71. Archived Project

第一版规则：

```text
Default Global Search
→ exclude Archived Project

Archived Filter / Scope
→ may include Archived Project
```

同时：

- Search Index 必须保留足够 Lifecycle Metadata 支持过滤。
- 如果返回 Archived 结果，结果必须明确标识 `Archived`。
- Search 不能自行把 Archived 当成 Deleted，也不能绕过当前 Permission。

---

## 72. Named Version Search

第一版命名 History Version 可以通过：

```text
History UI
```

查找。

不进入普通正文 Search。

以后可以增加：

```text
version name search
```

但与 Current Resource Search 分开。

---

## 73. Search Analytics

可以收集：

```text
query latency
zero result rate
click-through
filter usage
```

用于优化搜索。

但不得把：

```text
私密搜索词
Resource 内容
```

无边界地发送到外部 Analytics。

需要遵守隐私策略。

---

## 74. Abuse Protection

Search API 必须具备：

```text
Rate Limit
Query Complexity Limit
Bot Protection（需要时）
```

不能允许用户通过大量模糊查询：

```text
枚举整个 Workspace 内容
```

越权或拖垮系统。

---

## 75. Cache

允许缓存：

```text
public/common metadata
query result
suggestion
```

但权限敏感 Search Result 缓存必须包含：

```text
permission scope
actor context
```

或在返回前重新过滤。

不能让 User A 的缓存结果直接返回给 User B。

---

## 76. Search Result Cache

对于高动态协作内容：

```text
Result Cache TTL
```

不能过长。

具体策略由索引延迟和用户体验确定。

当前 Resource 内搜索仍然优先使用本地状态。

---

## 77. Observability

至少监控：

```text
search query count
search latency
search error
zero result rate
index queue depth
index lag
index task duration
index task failure
stale task skipped
reindex duration
reindex failure
permission filter latency
permission denial
search engine health
index document count
index storage size
semantic query latency
embedding backlog
OCR / transcript backlog
```

---

## 78. Search Freshness 指标

至少需要能够知道：

```text
Resource 最新状态时间
Index 最新状态时间
```

从而计算：

```text
Index Lag
```

不能只监控 Search API 响应速度，却不知道结果已经落后多久。

---

## 79. 第一版不做

第一版暂不要求：

```text
完整 IDE Symbol Search
Cross-reference Engine
Code Intelligence Graph
所有历史版本全文索引
法证级逐版本搜索
全局公开搜索
跨 Workspace 无权限搜索
自研全文搜索引擎
自研向量数据库
```

优先使用成熟 Search / Vector 基础设施。

---

## 80. 核心验收场景

### 场景 1：Workspace 全文搜索

用户搜索：

```text
Yjs 协作
```

结果：

- 返回有权限的 Resource
- 返回匹配 Snippet
- Document 结果能定位对应 Node
- 不返回无权限 Resource

---

### 场景 2：中文搜索

Resource 内容：

```text
统一实时协作协议
```

搜索：

```text
实时协作
```

可以正常命中。

中英文混排也能合理搜索。

---

### 场景 3：当前 Document 查找

用户刚输入一段尚未进入 Global Index 的内容。

使用：

```text
Ctrl + F
```

结果：

```text
立即找到
```

不等待 Search Index。

---

### 场景 4：实时高频编辑

多人持续输入。

结果：

- Realtime 不被 Search Index 阻塞
- Index Task 合并 / Debounce
- 最终 Current State 可搜索

---

### 场景 5：Rename

Resource 名称改变。

结果：

- 新名称可以搜索
- 旧名称最终不再作为当前名称命中
- 正文不需要全量重建

---

### 场景 6：Move

Resource 从 Folder A 移动到 Folder B。

结果：

- Search Result Location 更新
- resourceId 不变
- 正文结果不丢

---

### 场景 7：Permission Revoke

User A 原本能访问 Resource。

权限被移除。

结果：

- 即使 Search Index 权限 Metadata 尚未完成刷新
- Query-time Permission 也不返回该 Resource

---

### 场景 8：Trash

Resource 进入 Trash。

结果：

```text
普通 Search
→ 不再返回
```

Trash Scope 中仍可按产品规则查找。

---

### 场景 9：Restore

Resource Restore。

结果：

- 重新进入普通搜索
- 保留同一个 resourceId
- Index 最终恢复

---

### 场景 10：Search Engine 故障

Search Engine 暂时不可用。

结果：

- Resource 继续编辑
- Realtime 正常
- Persistence 正常
- Index Task 可积压
- Search 恢复后补齐

---

### 场景 11：Event 丢失

某 ResourceContentChanged 没被 Search Consumer 正常处理。

结果：

```text
Reconciliation / Reindex
↓
最终修复
```

不能永久无法搜索。

---

### 场景 12：旧 Task 乱序

Index Task v10 晚于 v15 执行。

结果：

```text
v10 不会覆盖 v15
```

最终 Index 是新状态。

---

### 场景 13：Full Reindex

Search Schema 升级。

结果：

- 新 Index 后台建立
- 线上旧 Index 继续查询
- Catch Up 后平滑切换
- 不需要停止 Resource 编辑

---

### 场景 14：大型 Workspace

Workspace 有大量 Resource。

结果：

- Search 分页稳定
- 不加载所有 Y.Doc
- Query / Index 都具备 Backpressure
- 不依赖单机内存

---

### 场景 15：Semantic Search 故障

Vector Service 不可用。

结果：

```text
Keyword Search
仍然正常工作
```

---

### 场景 16：AI Search

AI 在 User A 权限上下文中检索。

结果：

- 只能搜索 User A 有权访问的内容
- 返回 Resource / Node Source Reference
- 不能以系统身份读取私密 Resource

---

## 81. 本地 AI 实现自由度

本设计不规定：

- 使用 Elasticsearch / OpenSearch / Meilisearch / Typesense / PostgreSQL FTS 等哪一种
- 使用哪一种 Vector Database
- 中文 Analyzer 具体实现
- Ranking 权重
- Fuzzy 阈值
- Index Debounce 时间
- Chunk 大小
- Embedding Model
- Worker 数量
- Search Cache 产品
- Cursor Pagination 的底层字段
- Event Bus 产品

本地 AI 可以根据项目规模、技术栈、部署环境和压测结果选择。

但必须满足本设计的功能、安全、权限、恢复、扩展和性能要求。

---

## 82. 架构硬约束

1. Search 是派生系统，不是 Source of Truth。
2. Current Resource Find 与 Global Search 分离。
3. Search Index 不能阻塞 Realtime Collaboration。
4. 第一版必须支持 Workspace / Project / Folder / Resource Scope 搜索。
5. 第一版必须支持 Resource Metadata 和 Current Resource Content 搜索。
6. Search Result 必须经过当前 Permission 过滤。
7. 权限过期索引不能成为数据泄漏窗口。
8. Search 必须原生支持 Unicode 和中文等非英语内容。
9. Search Index 使用稳定 resourceId / NodeRef 定位真实对象。
10. Resource Move / Rename 不改变 Search Identity。
11. Resource Trash / Delete 必须最终从普通 Search 移除。
12. History 全量正文第一版不进入普通 Global Search。
13. Realtime 高频变化必须 Debounce / Coalesce 后进入 Index。
14. 过期 Index Task 不能覆盖较新 Index 状态。
15. Search Schema 必须版本化并支持无停机 Rebuild。
16. Event Pipeline 之外必须有 Reconciliation / Reindex 修复能力。
17. Search Engine 故障不能拖垮 Resource Editing / Permission / Persistence。
18. Semantic Search 是可插拔增强，不是基础 Keyword Search 的单点依赖。
19. AI / RAG 使用 Search 时必须继承当前 Actor Permission。
20. 大型 Index / Reindex 操作使用 Async Task。
21. Search 高吞吐路径必须支持 Backpressure。
22. 大型 Payload 不直接进入 Search Event。
23. 每个 Resource Type 通过 Search Adapter 提供可搜索表示。
24. Search 模块遵守 Unified Module Communication Design。
25. 第一版不自研全文搜索引擎或向量数据库。

---

## 83. 最终模型

```text
                Source of Truth
                      │
        ┌─────────────┼─────────────┐
        ▼             ▼             ▼
     Resource      Permission      Asset
        │
        │ Events
        ▼
  Indexing Pipeline
        │
        ├── Extract
        ├── Normalize
        ├── Permission Metadata
        ├── Chunk（可选）
        └── Index
             │
             ├── Keyword Index
             └── Vector Index（可选）
                      │
                      ▼
                  Search API
                      │
                      ├── Scope
                      ├── Filter
                      ├── Permission
                      ├── Ranking
                      └── Result
                           │
                           ▼
                    ResourceRef / NodeRef
```

实时编辑路径：

```text
User Edit
↓
Yjs
↓
Realtime / Persistence

           └── 异步 Index Trigger
```

不是：

```text
User Edit
↓
等待 Search Index
↓
继续编辑
```

系统必须保证：

> Search 可以稍后追上，但不能拖住编辑；Search 可以重建，但不能成为真相；Search 可以很强，但永远不能绕过权限。
