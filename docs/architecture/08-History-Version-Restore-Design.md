# History & Version Restore Design

## 1. 目标

本设计定义 Resource 的历史查看、版本比较和安全恢复能力。

本模块解决：

> 用户如何理解一个 Resource 过去发生了什么、查看过去状态、比较变化，并安全恢复到历史状态，同时不破坏当前实时协作。

本模块不负责：

- 当前状态如何可靠落盘
- Yjs 实时同步
- Permission 的基础授权模型
- Block / Node Identity
- Workspace / Project 组织结构

这些分别由 Persistence、Realtime Collaboration、Permission、Block / Node Identity、Resource Collaboration 负责。

---

## 2. 核心产品能力

第一版正式支持：

```text
自动历史
命名版本
历史时间线
历史预览
版本 Diff
安全恢复
恢复可逆
历史权限控制
历史审计
```

用户不需要手动点击“保存”才能产生历史。

实时协作继续保持自动同步。

---

## 3. Persistence 与 History 的边界

必须明确：

```text
Persistence Checkpoint
≠
User Version
```

Persistence 的：

```text
Durable Journal
Checkpoint
Compaction
```

服务于：

```text
当前状态可靠恢复
服务重启恢复
Session 冷启动
控制恢复成本
```

History 服务于：

```text
人类理解过去发生了什么
查看过去状态
比较变化
恢复过去版本
审计重要操作
```

两者可以复用底层数据，但不能被设计成同一个产品概念。

---

## 4. 历史来源

History 可以基于以下信息形成：

```text
Resource 的持久化状态变化
命名版本
恢复操作
重要结构变化
重要业务事件
```

不要求每一个 Yjs Update 都直接成为一个用户可见版本。

例如用户连续输入：

```text
a
ab
abc
abcd
```

不能直接在历史面板显示成四个版本。

History 必须把底层高频变化整理成人类可理解的历史节点。

---

## 5. 自动历史聚合

系统需要自动把连续编辑聚合成历史记录。

聚合可参考：

- 时间间隔
- 编辑活跃度
- 参与用户
- 修改规模
- 是否发生明显结构变化
- 是否发生重要操作
- Resource Type 特性

具体聚合算法和阈值由实现与产品测试决定。

架构要求：

> History 面板不能直接暴露底层高频 Journal 粒度。

---

## 6. 自动历史记录

自动历史至少应该表达：

```text
时间
参与者
变化摘要
历史状态
```

例如：

```text
今天 10:32
2 位用户编辑
修改了 3 个段落

今天 10:18
User A 编辑
更新了标题和正文

昨天 22:41
命名版本：API 设计确认
```

历史摘要应适合当前 Resource Type。

---

## 7. 命名版本

用户可以显式创建命名版本。

例如：

```text
需求评审前
正式发布版
v1.0 草稿
演示版本
```

命名版本是：

```text
History Marker
```

不是：

```text
新的独立 Resource
新的 Y.Doc
Git Branch
```

创建命名版本不能中断实时协作。

---

## 8. 命名版本内容

命名版本至少支持：

```text
name
description（可选）
creator
createdAt
target historical state
```

用户命名不能改变底层 Resource Identity。

---

## 9. 历史时间线

History UI 必须提供 Resource 级时间线。

时间线至少支持：

- 按时间浏览
- 显示命名版本
- 显示重要恢复操作
- 显示主要参与者
- 打开某个历史状态
- 比较历史状态
- 恢复历史状态

底层 Journal Segment、Checkpoint ID 等内部实现不直接暴露给普通用户。

---

## 10. 历史预览

用户打开历史状态时：

```text
进入 History Preview
```

而不是：

```text
把当前 Y.Doc 切换成旧状态
```

History Preview 必须是只读隔离状态。

预览过程中：

- 当前 Resource 继续实时协作
- 其他用户继续编辑
- 当前 Y.Doc 不被历史预览覆盖
- Presence 不被旧版本状态污染

---

## 11. 历史预览来源

历史预览可以由：

```text
历史基准状态
+
必要增量
```

重建。

具体是否使用：

```text
Checkpoint
Journal
History-specific Materialization
Cache
```

由实现决定。

但必须保证：

> History Preview 不成为当前协作状态的第二个可修改 Source of Truth。

---

## 12. 预览性能

历史预览不能要求：

```text
从 Resource 创建第一天开始完整重放所有变化
```

系统应能通过：

- Checkpoint
- 历史缓存
- Materialized State
- 合理的索引

控制历史打开速度。

具体策略由压力测试决定。

---

## 13. Diff

第一版支持：

```text
历史版本 ↔ 当前版本
历史版本 ↔ 历史版本
```

的比较。

Diff 是 Resource Type 相关能力。

不同 Resource Type 可以提供不同表现。

---

## 14. Document Diff

Document Resource 应提供适合结构化文档的 Diff。

至少能够表达：

```text
新增
删除
修改
移动
```

对于可识别 Node：

```text
优先结合 nodeId
```

判断逻辑节点变化。

不能只通过纯文本位置判断所有变化。

---

## 15. Code / Text Diff

Code、Markdown、Text Resource 可以使用成熟文本 Diff。

至少支持：

```text
行级 Diff
新增
删除
修改
```

具体编辑器和算法由实现选择。

不要求所有 Resource 使用同一个 Diff 算法。

---

## 16. Unknown / Future Resource Type

新增 Resource Type 时，需要提供自己的 History Adapter。

至少负责：

```text
如何生成可预览状态
如何比较历史状态
如何描述变化摘要
```

如果某个 Resource Type 暂时没有高级 Diff：

```text
仍然必须支持历史预览和安全恢复
```

可以退化为通用状态比较。

---

## 17. 恢复的产品语义

“恢复到这个版本”表示：

> 让当前 Resource 的内容变成历史状态所表达的内容。

恢复不是：

```text
回到过去并删除之后所有历史
```

也不是：

```text
直接替换数据库里的最新 Checkpoint
```

恢复本身是一项新的当前修改。

---

## 18. 恢复必须产生新的历史

例如：

```text
Current
= Version 20

Restore
→ Version 8
```

结果不是：

```text
系统时间线回到 Version 8
```

而是：

```text
Version 21
内容来自 Version 8
```

因此恢复操作本身继续存在于历史时间线中。

---

## 19. 恢复可逆

恢复前的当前状态必须继续可访问。

例如：

```text
Current A
↓
Restore Historical B
↓
Current becomes B
```

之后用户仍然可以：

```text
查看恢复前的 A
或
再次恢复 A
```

不能因为一次 Restore 永久覆盖掉恢复前状态。

---

## 20. 恢复与实时协作

Resource 正在多人编辑时仍允许执行 History Restore。

系统不能要求：

```text
所有人退出
锁住整个 Resource
关闭 WebSocket
```

恢复必须作为当前 Resource 的受控新修改进入实时协作模型。

恢复完成后：

```text
所有在线客户端
↓
通过正常 Yjs / Resource Sync
↓
看到新当前状态
```

---

## 21. 恢复不能绕过 Yjs

History Restore 不能：

```text
直接修改数据库正文
↓
让在线 Y.Doc 完全不知道
```

最终恢复必须进入当前协作状态。

具体实现可以由本地 AI 选择：

- 生成受控 Resource Change
- 通过 Document / Resource Adapter 应用状态
- 形成 Yjs 更新

但不能创建第二条“数据库直接覆盖正文”的修改路径。

---

## 22. Restore 期间的并发

Restore 过程中其他用户可能继续编辑。

系统必须明确定义恢复作用的目标状态，并安全处理并发。

产品层目标：

- 不静默丢失用户已经产生的当前修改
- 不出现客户端永久分叉
- 最终所有参与者重新收敛
- Restore 结果可追踪
- Restore 失败不能留下半恢复状态

具体事务、锁、ChangeSet 或协调机制由本地 AI 根据 Resource Type 实现。

---

## 23. Restore 是高风险操作

Restore 必须：

- 检查权限
- 记录审计
- 支持幂等
- 支持失败状态
- 支持重试保护
- 不允许因为请求超时重复恢复多次

如果 Restore 较大，应进入统一 Async Task 模型。

---

## 24. Restore Preview

在执行 Restore 前，产品应允许用户确认：

```text
目标版本
版本时间
主要变化
当前版本差异
```

大型或高风险 Restore 应优先提供 Diff Preview。

不要求每次都弹出复杂确认框，但产品必须避免用户误操作后完全不知道会发生什么。

---

## 25. Restore 后通知

Restore 成功后：

```text
HistoryRestored
```

作为系统 Event 发布。

相关模块可以据此：

- 刷新 Search Index
- 更新 AI Index
- 记录 Audit
- 刷新 Preview
- 更新派生数据

Event 语义遵守 Unified Module Communication Design。

---

## 26. History 与 Permission

History 必须使用统一 Permission System。

History 本身不定义第二套 Role Matrix。第一版普通 History Viewer / Restore Capability 统一由 `07-Permission-Access-Control-Design.md` 定义为 `Edit / Manage / Owner`；History 模块只消费对应 Capability。

不能通过 History 读取用户当前没有权限读取的 Resource。

---

## 27. 权限变化后的历史访问

如果用户失去 Resource 访问权限：

```text
不能继续通过旧 History URL
```

访问历史内容。

History 不能成为绕过当前权限的后门。

---

## 28. History 与 Audit

History 与 Audit 是相关但不同的能力。

History 主要回答：

```text
Resource 内容过去是什么
```

Audit 主要回答：

```text
谁执行了什么关键操作
```

例如：

```text
成员权限变化
分享链接创建
Owner 转移
永久删除
```

属于 Audit。

不要求全部混进普通版本时间线。

---

## 29. 编辑参与者

自动历史可以显示：

```text
主要参与者
```

但不能要求每个字符都永久绑定一个用户形成昂贵的逐字符审计。

第一版目标是：

```text
可理解的编辑参与信息
```

而不是：

```text
法证级逐键盘记录
```

---

## 30. 变化摘要

History 可以生成：

```text
修改了标题
新增 3 个段落
删除 1 个代码块
修改 24 行代码
```

等摘要。

摘要是派生数据。

如果摘要生成失败：

```text
不能影响 History State 本身的可靠性
```

摘要可以异步生成。

---

## 31. AI 历史摘要

后续可以允许 AI 生成：

```text
这次版本主要改了什么
两个版本有哪些重要差异
```

但 AI Summary 只是辅助展示。

不能成为：

```text
版本真实状态
Diff 的唯一依据
Restore 的数据来源
```

---

## 32. History Storage

History 可以复用 Persistence 的：

```text
Checkpoint
Durable Journal
```

降低重复存储。

但允许为产品体验额外建立：

```text
History Index
Version Marker
Materialized Historical State
Diff Cache
Summary Cache
```

具体存储设计由实现决定。

---

## 33. History Index

系统应建立可高效查询的历史索引。

至少支持：

- 按 Resource 查询时间线
- 按时间范围查询
- 快速定位命名版本
- 快速定位 Restore 记录
- 找到预览所需恢复起点

不能每次打开历史面板都扫描完整 Journal。

---

## 34. 历史数据生命周期

历史不能无限无策略增长。

系统需要支持：

```text
Retention Policy
```

可以根据产品版本、部署类型或企业策略决定：

- 自动历史保存多久
- 命名版本保存多久
- Restore 记录保存多久
- Audit 保存多久
- 已删除 Resource 的历史保留多久

第一版不必暴露复杂策略 UI。

但底层不能假设所有历史永久保存。

---

## 35. 命名版本保护

命名版本默认应比普通自动历史拥有更高保留优先级。

例如普通自动历史可以根据策略清理，而命名版本需要：

```text
明确策略
或
用户主动删除
```

后才进入回收。

具体保留周期由产品版本决定。

---

## 36. History GC

历史回收必须：

- 不破坏当前 Resource 恢复
- 不破坏受保护命名版本
- 不破坏必要 Audit
- 不产生断裂历史引用
- 不影响正在预览的历史任务

History GC 与 Persistence Compaction 可以协调，但不是同一件事。

---

## 37. Resource 删除

Resource 进入 Trash 后：

```text
History 默认继续保留
```

以支持恢复。

永久删除 Resource 时，History 数据按：

```text
Retention / Compliance Policy
```

最终清理。

不要在普通删除时立即物理销毁所有历史。

---

## 38. 历史缓存

允许缓存：

```text
Historical Preview
Diff
Timeline
Summary
```

提高体验。

但缓存不是 Source of Truth。

缓存丢失后必须可以重建。

---

## 39. 大型 History 请求

以下操作可能非常重：

```text
多年历史列表
大文档历史重建
大型 Diff
跨很远版本比较
大型 Restore
```

不能长时间占用同步请求。

应使用：

```text
Pagination
Lazy Load
Async Task
Background Compute
```

等方式控制负载。

具体实现由本地 AI 选择。

---

## 40. 多 Resource History

History 默认以：

```text
Resource
```

为版本边界。

不能假设：

```text
Project
```

天然拥有一个跨所有文件的统一版本。

如果未来需要：

```text
整个 Project 发布版本
跨多个 Resource 的 Release Snapshot
AI ChangeSet 历史
```

应由更高层：

```text
ChangeSet / Release / Operation
```

设计。

不要破坏 Resource 独立版本边界。

---

## 41. AI 多文件修改与 History

如果 AI 同时修改多个 Resource：

```text
main.ts
app.ts
README.md
```

每个 Resource 都产生自己的 History 变化。

同时更高层 Task / ChangeSet 可以记录：

```text
这三次 Resource 修改属于同一次 AI Operation
```

History 不需要把多个 Resource 强行合并成一个 Y.Doc 版本。

---

## 42. Version Identity

用户可见的历史版本必须有稳定身份。

用于：

```text
打开
分享内部链接
Diff
Restore
审计关联
```

具体 ID 格式由实现决定。

Version ID 不参与 Yjs 冲突处理。

也不替代：

```text
resourceId
nodeId
```

---

## 43. History API / Communication

History 模块遵守：

```text
Unified Module Communication Design
```

主要交互语义：

### Query

```text
查询 Timeline
查询 Version
读取 Preview
读取 Diff
```

### Command

```text
CreateNamedVersion
RestoreVersion
DeleteNamedVersion
```

### Event

```text
NamedVersionCreated
HistoryRestored
NamedVersionDeleted
```

### Async Task

```text
Large Diff
Large Restore
Historical Materialization
```

具体接口字段由本地 AI 根据 Contract 统一定义。

---

## 44. History 与 Realtime 的关系

Realtime 负责：

```text
当前状态
当前多人协作
```

History 负责：

```text
过去状态
```

History Preview 不加入当前 Resource Session。

History Restore 最终必须进入当前 Resource 的实时状态。

两者不能维护两个同时可写的当前文档。

---

## 45. History 与 Persistence 的关系

Persistence 提供：

```text
可靠恢复当前状态的底层能力
```

History 可以消费：

```text
Checkpoint
Journal
Durable Boundary
```

但不能修改 Persistence 的核心可靠性链。

History 功能故障不能导致：

```text
当前 Resource 无法编辑
当前 Resource 无法持久化
```

---

## 46. History 故障隔离

以下故障：

```text
History Timeline 加载失败
Diff 失败
Summary 失败
Preview Cache 失败
```

不能影响：

```text
Realtime Editing
Permission
Persistence
Resource Current State
```

History 是重要产品能力，但不是当前编辑热路径依赖。

---

## 47. 可观测性

至少监控：

```text
history timeline latency
history preview latency
history materialization latency
diff duration
diff failure
restore duration
restore failure
restore conflict / retry
named version count
history storage size
history cache hit rate
history GC duration
history retention cleanup
```

Restore 属于高风险能力，需要单独监控成功率和失败原因。

---

## 48. 安全要求

History 至少需要保证：

- 访问历史前重新检查当前权限
- Version ID 不可用于绕过 Resource 权限
- Restore 需要服务端鉴权
- Restore 需要审计
- 历史预览不能执行 Resource 中潜在危险脚本
- 历史内容不能通过缓存跨用户泄露
- 已删除访问权限必须影响历史访问
- Diff / Preview 不能返回用户无权访问的 Asset 内容

---

## 49. 必须避免

不得：

- 把 Persistence Checkpoint 直接当用户版本展示
- 每个 Yjs Update 都生成一个用户可见版本
- History Preview 修改当前 Y.Doc
- Restore 直接覆盖数据库而绕过实时协作
- Restore 删除之后的所有历史
- Restore 后无法回到恢复前状态
- 为了 Restore 锁住整个 Resource 很长时间
- History 故障阻塞当前编辑
- History URL 绕过 Resource 权限
- 把 Project 默认当作一个单版本对象
- 把 AI Summary 当成真实 Diff
- 无限永久保存所有历史而没有 Retention 设计

---

## 50. 第一版不做

第一版暂不实现：

```text
Git Branch
Merge Request
Cherry-pick
Rebase
跨 Resource 原子版本
复杂 Release Management
法证级逐字符作者追踪
永久保存全部自动历史
```

这些能力后续在产品确有需求时独立设计。

---

## 51. 核心验收场景

### 场景 1：自动历史

用户持续编辑 Resource。

结果：

- 不需要手动保存
- History 自动形成可浏览记录
- 不会每次按键产生一个版本

---

### 场景 2：命名版本

用户创建：

```text
正式评审版
```

结果：

- 当前实时协作不中断
- Timeline 中出现命名版本
- 可以预览、Diff、Restore

---

### 场景 3：历史预览

用户打开昨天版本。

同时其他用户继续编辑当前 Resource。

结果：

- 历史 Preview 保持稳定
- 当前 Resource 继续实时变化
- 二者互不覆盖

---

### 场景 4：Document Diff

两个 Document 版本存在：

```text
新增段落
移动 Block
修改标题
```

结果：

> Diff 能用适合结构文档的方式展示主要变化，而不是只显示一整页纯文本变化。

---

### 场景 5：Code Diff

两个 Code Resource 历史版本。

结果：

```text
正常展示行级新增 / 删除 / 修改
```

---

### 场景 6：Restore

用户从当前版本恢复到旧版本。

结果：

```text
旧内容成为新的当前状态
↓
在线用户收到实时变化
↓
History 中记录 Restore
```

---

### 场景 7：Restore 可逆

Restore 完成后用户发现不合适。

结果：

```text
仍可找到 Restore 前状态
↓
再次 Restore
```

---

### 场景 8：多人在线 Restore

3 个用户同时编辑。

有权限用户执行 Restore。

结果：

- 不要求其他用户退出
- 最终所有客户端收敛
- 不产生永久分叉
- Restore 有明确历史记录

---

### 场景 9：Restore 请求超时

客户端发起 Restore 后网络超时。

结果：

```text
不能无保护重复执行
```

应通过：

```text
requestId / taskId
```

确认最终状态。

---

### 场景 10：权限失效

用户打开 History 页面后被移除 Resource。

结果：

- 后续 History Query 拒绝
- 不能继续通过 Version URL 获取内容

---

### 场景 11：History 服务故障

History 服务暂时不可用。

结果：

```text
当前实时编辑继续
Persistence 继续
Permission 继续
```

---

### 场景 12：大历史 Resource

Resource 已使用数年。

结果：

- Timeline 仍可分页加载
- Preview 不从第一条 Update 开始全量重放
- Diff / Restore 可以进入异步任务
- 不造成实时编辑明显卡顿

---

### 场景 13：Resource 删除

Resource 进入 Trash。

结果：

```text
History 仍保留
```

用于恢复。

---

### 场景 14：History Retention

普通自动历史超过保留策略。

结果：

- 可以被后台回收
- 命名版本按更高优先级策略保留
- 当前状态恢复链不受影响

---

## 52. 本地 AI 实现自由度

本设计不规定：

- History 表如何设计
- Version ID 格式
- 使用哪种 Diff 库
- 自动历史具体聚合阈值
- History Materialization 使用哪种缓存
- Retention 的固定天数
- Checkpoint 与 History Index 的具体关联方式
- Restore 内部事务实现
- 是否使用独立 History Service

本地 AI 可以根据当前项目架构和性能测试选择实现。

但必须满足本设计的产品功能、边界、安全性和验收条件。

---

## 53. 架构硬约束

1. `Persistence Checkpoint` 与 `User Version` 必须分离。
2. History 自动形成，不依赖手动保存按钮。
3. 底层高频 Yjs Update 不直接一一映射为用户可见版本。
4. 第一版支持自动历史、命名版本、Preview、Diff、Restore 和 Restore 可逆。
5. History Preview 必须与当前可编辑 Y.Doc 隔离。
6. History Preview 只读，不参与当前 Awareness。
7. Diff 根据 Resource Type 选择合适实现。
8. Document Diff 应优先利用稳定 Node Identity。
9. Restore 是新的当前修改，不是删除之后历史回到过去。
10. Restore 前状态必须继续可访问。
11. Restore 最终必须进入当前 Resource 协作状态，不能绕过 Yjs / Resource 修改路径。
12. Restore 必须遵守 Permission、幂等、审计和统一通信规范。
13. 大型 Restore / Diff 可以使用 Async Task。
14. History 可以复用 Journal / Checkpoint，但不能破坏 Persistence 可靠性链。
15. History 故障不能阻塞 Realtime Editing 或 Persistence。
16. History 默认以 Resource 为版本边界。
17. 跨 Resource 版本由更高层 ChangeSet / Release / Operation 处理。
18. History 必须支持 Retention 和 GC。
19. 命名版本默认具有比普通自动历史更高的保留优先级。
20. History 访问必须重新检查当前 Resource 权限。
21. 第一版不实现 Git Branch / Merge / Rebase / Cherry-pick。
22. History 模块遵守 Unified Module Communication Design。

---

## 54. 最终模型

```text
                   Current Resource
                         │
                         │ Realtime Edit
                         ▼
                       Y.Doc
                         │
                         ▼
                Persistence Journal
                         │
              ┌──────────┴──────────┐
              │                     │
              ▼                     ▼
         Checkpoint            History Index
                                    │
                        ┌───────────┼───────────┐
                        ▼           ▼           ▼
                     Timeline     Preview      Diff
                                                │
                                                ▼
                                             Restore
                                                │
                                                ▼
                                      Current Resource Change
                                                │
                                                ▼
                                               Yjs
```

产品理解：

```text
Persistence
保证“现在不会丢”

History
保证“过去找得回来、看得懂、恢复得安全”
```

两者共享底层数据能力，但职责保持独立。
