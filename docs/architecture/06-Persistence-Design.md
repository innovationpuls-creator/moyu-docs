# Persistence Design

## 1. 目标

本设计定义实时协作数据如何从运行中的 `Resource Session` 可靠进入长期存储，并在服务重启、Session 回收、网络中断或节点故障后恢复。

本模块不负责：

- 实时多人冲突合并
- Presence / Cursor / Selection
- 历史版本 UI
- Diff / Audit 产品能力
- 具体数据库表、ORM、队列库或云服务选型

这些分别由 Realtime Collaboration、History、Permission 和具体实现负责。

本模块只规定：

> 实时协作数据必须怎样保存、压缩、恢复和回收，才能同时满足数据可靠、恢复快速、用户无感和长期运行成本可控。

---

## 2. 核心架构

持久化采用成熟实时协作系统常见的：

```text
Hot State
+
Durable Update Journal
+
Checkpoint
+
Compaction
+
Client Local Recovery
```

整体关系：

```text
Client Local Y.Doc
        │
        ├── Local Persistence
        │
        └── Realtime Sync
                ↓
        Resource Session
          Hot Y.Doc
                │
        ┌───────┴────────┐
        ↓                ↓
 Remote Clients   Durable Update Journal
                         │
                         ↓
                    Checkpoint
                         │
                         ↓
                 Long-term Storage
```

其中：

- `Hot State` 负责当前实时协作
- `Durable Update Journal` 负责可靠记录增量变化
- `Checkpoint` 负责缩短恢复路径
- `Compaction` 负责控制长期数据规模和恢复成本
- `Client Local Recovery` 负责断网、刷新、客户端崩溃后的本地恢复

---

## 3. 术语约束

### 3.1 Durable Update Journal

以下简称：

```text
Journal
```

表示某个 Resource 已可靠持久化的 Yjs 增量变化流。

Journal 是当前状态可靠恢复的主链。

---

### 3.2 Checkpoint

`Checkpoint` 表示：

> 某个已知持久化边界上的 Resource 完整可恢复状态。

Checkpoint 的目的：

- 加速 Resource 冷启动
- 避免从 Resource 创建以来重放全部 Update
- 降低长期 Journal 恢复成本
- 为 Compaction 提供安全基准

本项目中不要把这个概念命名为 Yjs `Snapshot`。

`Checkpoint` 与 Yjs 自身的 `Snapshot` 数据结构不是同一个概念。

---

### 3.3 Compaction

`Compaction` 表示：

> 在已经存在可靠 Checkpoint 的前提下，安全减少旧 Journal 恢复负担和存储负担。

Compaction 不能成为数据可靠性的前置条件。

---

## 4. 可靠性状态

系统必须区分三个不同状态：

```text
Local
Synced
Durable
```

### Local

修改已经进入当前客户端的本地 Y.Doc。

用户界面立即看到。

### Synced

修改已经通过实时协作传播到服务端或其他协作者。

### Durable

修改已经进入可靠持久化链，即使当前 Resource Session 或协作服务进程消失，也能从持久化系统恢复。

三者不能被当成同一个状态。

---

## 5. 用户输入不得等待持久化

用户编辑路径必须保持：

```text
User Input
↓
Local Editor
↓
Local Y.Doc
↓
UI 立即更新
```

持久化位于后台：

```text
Yjs Update
↓
Realtime Session
↓
Journal
```

禁止：

```text
User Input
↓
等待数据库写入
↓
UI 才更新
```

也禁止：

```text
远端协作
↓
等待 Checkpoint / Compaction
↓
才继续广播
```

---

## 6. 持久化窗口

默认要求：

> 持久化窗口尽可能短，但不得阻塞实时编辑主路径。

架构阶段不写死固定毫秒数。

具体目标由：

- 部署环境
- 存储性能
- 网络延迟
- 压力测试
- 故障恢复测试

共同确定。

系统必须能监控当前：

```text
未 Durable 的 Update 数量
未 Durable 的数据量
最老 Pending Update 的等待时间
```

不能用“异步保存”掩盖长时间未持久化的问题。

---

## 7. Journal 是持久化主链

每个 Resource 必须拥有独立的逻辑 Journal。

Journal 需要满足：

- 可以可靠追加新的 Yjs Update
- 可以判断哪些 Update 已经 Durable
- 可以识别某个 Checkpoint 覆盖到哪个持久化边界
- 服务重启后仍能读取
- 重复恢复不会破坏最终 Yjs 状态
- 不依赖某个客户端持续在线

Journal 逻辑上按 Resource 隔离。

一个高流量 Resource 不应阻塞其他 Resource 的持久化。

---

## 8. Journal 不要求一条网络 Update 对应一条存储记录

为了效率，系统允许：

```text
Update A
Update B
Update C
↓
短暂聚合 / 合并
↓
一个 Durable Journal Segment
```

要求：

- 不扩大到明显的持久化延迟
- 不改变最终 Yjs 状态
- 不静默丢失正文修改
- 合并失败时可以安全重试
- 具体批量大小和时间窗口由压测决定

因此：

> Journal 的恢复语义必须基于 Yjs 状态，而不是依赖“用户每次按键对应一条数据库记录”。

---

## 9. Journal Cursor

持久化系统需要一个仅用于恢复管理的逻辑边界。

它可以表示：

```text
Checkpoint 覆盖到哪里
哪些 Journal 已经 Durable
恢复时从哪里继续
哪些旧 Journal 可以进入 Compaction
```

具体实现可以是：

```text
sequence
offset
cursor
segment id
```

由本地 AI 根据存储方案选择。

这个 Cursor：

> 不是文档版本号，不参与 CRDT 冲突判断，也不能重新引入 `baseVersion` / `blockVersion`。

---

## 10. Checkpoint 的职责

Checkpoint 不是每次编辑的保存操作。

它只负责：

```text
降低恢复成本
+
控制 Journal 长期增长
```

恢复路径：

```text
Latest Verified Checkpoint
+
Checkpoint 之后的 Durable Journal
↓
恢复 Resource Y.Doc
```

没有新 Checkpoint 时，只要 Journal 完整，Resource 仍然必须可恢复。

---

## 11. Checkpoint 触发策略

不采用单一固定时间作为唯一规则。

允许综合考虑：

- Journal 累计数据规模
- Journal 累计段数
- 从最近 Checkpoint 恢复所需成本
- Resource 活跃程度
- Session 长时间进入 IDLE
- 系统当前负载
- 后台任务容量
- 运维或维护触发

具体阈值不在架构阶段写死。

原则：

> Checkpoint 根据恢复成本和数据规模动态生成，而不是机械地“每 N 秒保存整份文档”。

---

## 12. Checkpoint 不能阻塞实时编辑

Checkpoint 必须作为后台能力运行。

生成过程中：

- 用户继续编辑
- Resource Session 继续同步
- Journal 继续追加
- 远端协作者继续收到实时 Update

不得因为正在生成 Checkpoint：

```text
锁住整个 Resource
暂停输入
暂停广播
停止接收 Update
```

如果实现需要极短的内部一致性切换，必须保证用户不可感知，并通过压力测试验证。

---

## 13. Checkpoint 必须对应明确的 Durable Boundary

一个 Checkpoint 必须能够回答：

> 它已经包含了 Journal 的哪些 Durable 状态？

不能出现：

```text
Checkpoint 已经发布
但不知道它覆盖到哪里
```

因此 Checkpoint 必须和某个明确的 Journal Durable Boundary 关联。

恢复时只重放该边界之后的 Journal。

---

## 14. Checkpoint 发布必须安全

新的 Checkpoint 只有在：

- 完整生成
- 数据可读取
- 能恢复出有效 Resource 状态
- 对应 Journal Boundary 明确
- 必要完整性校验通过

之后，才能成为：

```text
Latest Verified Checkpoint
```

生成失败时：

```text
继续使用旧 Checkpoint
+
完整 Journal
```

实时协作不受影响。

---

## 15. Compaction 安全顺序

Compaction 必须遵守：

```text
生成新 Checkpoint
↓
验证新 Checkpoint
↓
发布为可恢复 Checkpoint
↓
确认覆盖边界
↓
旧 Journal 才可以进入回收流程
```

禁止：

```text
先删除旧 Journal
↓
再尝试生成 Checkpoint
```

否则 Checkpoint 失败可能直接造成不可恢复的数据缺口。

---

## 16. 旧 Journal 不要求立即物理删除

Checkpoint 成功后，被覆盖的旧 Journal 可以：

```text
标记为可回收
↓
异步清理
```

是否立即删除、延迟删除或暂时保留，由：

- History 需求
- 审计需求
- 存储成本
- 运维恢复策略

共同决定。

Persistence 模块不假设旧 Journal 必须永久保存。

---

## 17. Resource 冷启动恢复

Resource Session 从 COLD / EVICTED 状态恢复时：

```text
读取 Latest Verified Checkpoint
↓
恢复基础 Yjs State
↓
读取 Checkpoint 之后的 Durable Journal
↓
重放 / 合并 Journal
↓
完成必要校验
↓
得到 Server Y.Doc
↓
Resource Session ACTIVE
```

随后客户端：

```text
通过 Yjs State Vector
↓
只补双方缺失状态
↓
进入 LIVE
```

不能使用整份 JSON 无条件覆盖客户端。

---

## 18. 没有 Checkpoint 时的恢复

新 Resource 或 Checkpoint 尚未生成时：

```text
Journal
```

仍然必须能够恢复当前状态。

Checkpoint 是加速恢复的能力，不是数据正确性的唯一来源。

---

## 19. Checkpoint 损坏时的恢复

如果最新 Checkpoint：

```text
损坏
无法读取
校验失败
```

系统必须：

```text
回退到上一个 Verified Checkpoint
+
之后完整 Journal
```

如果没有可用 Checkpoint，则根据完整 Journal 恢复。

不得因为单个 Checkpoint 损坏就直接判定整个 Resource 丢失。

---

## 20. 客户端本地恢复

可编辑客户端应具备本地 Yjs 状态恢复能力。

至少覆盖：

- 短暂断网
- 页面刷新
- 浏览器 / 客户端异常退出
- 服务端短时间不可用
- 尚未完全 Durable 的本地修改

具体本地存储技术由客户端实现决定。

架构要求：

> 本地未同步或未确认安全的协作状态不能因为一次普通重连而被服务端整份状态覆盖。

---

## 21. 断网恢复

网络断开后：

```text
Local Y.Doc
继续编辑
```

恢复连接后：

```text
Server 恢复自己的 Durable State
+
Client 保留自己的 Local State
↓
Yjs State Vector
↓
双方补齐缺失 Update
↓
最终收敛
```

禁止：

```text
Server wins
```

或：

```text
Client wins
```

这种整份覆盖模型。

---

## 22. Resource Session 与 Persistence 的关系

Resource Session 是：

```text
Hot State
```

Persistence 是：

```text
Durable State
```

两者不能混为同一个生命周期。

Resource Session 可以：

```text
创建
活跃
空闲
释放
重新加载
```

而 Resource 的 Durable State 必须持续存在。

---

## 23. Session 安全释放

Resource Session 进入 IDLE 后，不要求强制生成一个新的 Checkpoint。

安全释放的核心条件是：

> 当前服务端已接收并需要保存的正文 Update 已经进入 Durable Journal。

如果仍存在未 Durable 的正文 Update：

```text
Session 不能直接释放
```

可以：

- 等待持久化完成
- 重试
- 保持短期 Recovery State

具体机制由实现决定。

---

## 24. Checkpoint 不是 Session 释放前置条件

禁止设计：

```text
最后一个用户离开
↓
同步生成完整 Checkpoint
↓
生成成功
↓
才能释放 Session
```

这会在大量 Resource 同时空闲或服务扩缩容时形成集中负载。

正确规则：

```text
Journal 已 Durable
↓
Session 可安全回收
```

Checkpoint 可以随后由后台任务生成。

---

## 25. 持久化故障

当 Journal 暂时不可写时，系统不能：

```text
假装已经 Durable
```

也不能：

```text
无限把 Pending Update 堆在内存里
```

系统必须进入明确的 Degraded State。

允许短时间继续：

- local-first 编辑
- 客户端本地恢复
- Resource Session 内存协作

但随着 Durable Backlog 增长，系统必须有保护机制。

超过安全边界时，系统可以：

```text
停止接受新的共享写入
或
把 Resource 切换到受保护的只读 / 本地编辑状态
```

具体产品表现由实现决定。

核心要求：

> 数据安全优先于“看起来一切正常”。

---

## 26. 持久化恢复后

Journal 恢复可用后：

```text
Pending Update
↓
按 Resource 恢复 Durable 写入
↓
更新 Durable Boundary
↓
恢复正常状态
```

不同 Resource 应独立恢复。

一个 Resource 的异常不能要求所有 Resource 停止持久化。

---

## 27. 服务进程崩溃

服务进程崩溃后：

```text
Hot Y.Doc 消失
```

系统通过：

```text
Verified Checkpoint
+
Durable Journal
```

恢复服务端状态。

如果客户端还存在服务端崩溃前尚未 Durable 的修改：

```text
客户端重连
↓
State Vector
↓
重新补给服务端
```

这就是客户端 Local Recovery 的第二层保险价值。

---

## 28. 多服务实例

在集群环境中：

```text
Resource A
Resource B
Resource C
```

可以由不同协作节点处理。

持久化必须按 `resourceId` 保持逻辑隔离。

一个 Resource 的 Journal 写入、Checkpoint、Compaction 不得要求整个系统进入全局串行模式。

同一个 Resource 的 Durable Boundary 必须保持一致，不能由多个互不协调的 Writer 各自推进。

Resource Ownership 发生切换时必须具备 **stale-owner fencing**：

```text
Owner A / epoch N
↓ failover / reassignment
Owner B / epoch N+1
↓
Owner A 即使延迟恢复，也不能继续推进权威 Runtime State 或 Durable Boundary
```

每次有效 Ownership 必须存在可比较的 generation / epoch / fencing authority，或等价安全机制。Journal / Durable Boundary 的写入路径必须能够拒绝旧 Ownership 的后续权威写入。

具体 Resource Owner、Shard、Lease、Epoch 或 Fencing Token 的实现由本地 AI 选择，但单纯依赖“旧进程应该已经停了”不满足要求。

---

## 29. 并发原则

不同 Resource：

```text
允许并行持久化
允许并行 Checkpoint
允许并行恢复
```

同一个 Resource：

```text
允许持续接收实时 Update
```

但持久化状态边界、Checkpoint 发布和 Compaction 必须避免竞态导致：

```text
漏 Update
重复删除 Journal
Checkpoint 覆盖范围错误
```

具体锁、事务、Actor、单 Writer 等实现方式不在架构阶段指定。

---

## 30. Backpressure

如果存储速度低于实时 Update 产生速度：

```text
Durable Backlog
```

会增长。

系统必须能够：

- 监控 backlog
- 对 Journal 写入进行批量优化
- 限制单 Resource 占用
- 防止内存无限增长
- 在必要时进入 Degraded State

不能通过无限缓存解决长期持久化不足。

---

## 31. Large Resource

大型 Resource 的：

```text
Checkpoint
恢复
Compaction
```

不能阻塞其他普通 Resource。

系统需要能够：

- 限制单任务资源占用
- 分离后台任务执行
- 并发处理不同 Resource
- 对大型恢复和 Checkpoint 做调度

具体 Worker、Job Queue 和并发度由实现选择。

---

## 32. Resource 删除

删除 Resource 时，不应直接同步删除所有持久化数据。

需要给：

```text
Trash / Retention Policy
```

留下空间。

Resource 删除、回收站、永久删除的具体策略由 Resource / History / Permission 模块决定。

Persistence 需要支持：

- 暂停继续写入
- 保留必要恢复数据
- 最终按策略安全清理 Journal / Checkpoint

---

## 33. Schema Migration

如果 Resource Schema 需要迁移：

```text
旧 Durable State
↓
受控 Migration
↓
新 Durable State
```

Migration 不能由多个普通客户端同时自行执行。

迁移期间必须保证：

- 不产生两个不同版本的持久化真相
- 失败可以恢复
- 原状态在迁移确认前仍可回退
- 新 Checkpoint 只有验证后才能替代旧恢复基准

详细 Migration 规则仍以 Resource / Block Schema 设计为准。

---

## 34. Persistence 与 History 的边界

Persistence 解决：

> 当前 Resource 状态能不能可靠恢复。

History 解决：

> 用户能不能查看、比较、恢复过去某个时间点的状态。

两者可以复用：

```text
Journal
Checkpoint
```

中的部分数据。

但不得假设：

```text
Persistence Journal
=
完整产品 History
```

也不得为了 History 改变实时 CRDT 冲突模型。

---

## 35. Persistence 与 Awareness 的边界

以下内容不进入 Resource 正文持久化：

```text
Cursor
Selection
Online User
Temporary Presence
Pointer Position
Editing Indicator
```

它们属于 Awareness。

服务重启后重新建立即可。

---

## 36. Persistence 与 Asset 的边界

图片、视频、附件等大型二进制数据：

```text
Asset Storage
```

独立管理。

Yjs Resource 只保存：

```text
Asset Reference
```

Persistence Journal 不承担大型文件本体存储。

---

## 37. 完整性校验

持久化系统必须能够发现：

- Checkpoint 不可读取
- Journal Segment 损坏
- Journal Boundary 不连续
- Resource 与 Checkpoint 对应错误
- Schema 不兼容
- 恢复后状态无法通过必要校验

发现异常后：

```text
不得静默返回一个看似正常但不完整的 Resource
```

必须进入明确恢复或错误流程。

---

## 38. 可观测性

至少需要监控：

```text
durable lag
pending journal bytes
pending journal count
journal write latency
journal write failure
checkpoint duration
checkpoint size
checkpoint failure
compaction duration
recovery duration
journal replay size
resource cold start duration
local recovery / resync count
persistence degraded resource count
```

这些指标用于决定：

- 持久化窗口是否足够短
- Checkpoint 是否生成太频繁或太少
- Journal 是否增长过快
- Resource 冷启动是否开始变慢
- Storage 是否成为实时系统瓶颈

具体告警阈值由真实部署和压力测试确定。

---

## 39. 性能原则

必须满足：

- 用户输入不等待持久化
- 普通 Journal 写入尽快 Durable
- Journal 写入可以小批量合并
- Checkpoint 不占用实时编辑热路径
- Compaction 不阻塞 Resource 正常协作
- 大型 Resource 不明显拖慢其他 Resource
- 不同 Resource 可以并行持久化和恢复
- Session 回收不强制同步生成 Checkpoint
- 恢复成本不能随 Resource 年龄无限增长

---

## 40. 故障恢复原则

必须验证以下故障：

```text
协作服务进程突然退出
持久化服务短暂不可用
Checkpoint 生成中进程退出
Compaction 中途失败
最新 Checkpoint 损坏
Resource Session 被回收
客户端断网继续编辑
客户端和服务器同时拥有不同增量
多个客户端同时重连
```

所有场景都必须保证：

```text
不使用整份覆盖
不重新引入保存按钮
不重新引入传统版本冲突
不把 Awareness 当正文恢复
```

---

## 41. 核心验收场景

### 场景 1：正常持续编辑

多人持续编辑同一 Resource。

结果：

- 本地输入立即生效
- 远端实时同步
- Journal 持续进入 Durable
- 不需要手动保存

---

### 场景 2：服务端突然崩溃

Resource 正在编辑时服务端进程退出。

结果：

```text
重启
↓
Checkpoint + Durable Journal
↓
恢复 Y.Doc
↓
客户端 State Vector 补齐
↓
继续协作
```

---

### 场景 3：没有最新 Checkpoint

Checkpoint 很旧，但 Journal 完整。

结果：

> Resource 仍然能够正确恢复，只是恢复成本可能更高。

---

### 场景 4：Checkpoint 生成失败

后台 Checkpoint 失败。

结果：

- 实时协作继续
- Journal 继续写入
- 旧 Verified Checkpoint 继续可用
- 不删除对应旧 Journal

---

### 场景 5：Compaction 中途失败

结果：

- 已发布 Checkpoint 不被破坏
- 未确认安全的旧 Journal 不被删除
- Resource 仍然能够恢复

---

### 场景 6：最新 Checkpoint 损坏

结果：

```text
回退旧 Verified Checkpoint
+
Journal
↓
恢复 Resource
```

---

### 场景 7：最后一个用户离开

结果：

- 不强制立即生成 Checkpoint
- 先保证 Pending Update Durable
- 达到 Session 回收条件后释放 Hot State

---

### 场景 8：客户端断网继续编辑

结果：

- 本地编辑继续
- 本地状态保留
- 重连后通过 State Vector 双向补齐
- 不能被服务器整份覆盖

---

### 场景 9：持久化短暂不可用

结果：

- 系统明确进入 Degraded 状态
- 不伪造 Durable
- 不无限积压
- 存储恢复后可以继续推进 Journal
- 超过安全边界时具备保护性降级

---

### 场景 10：长期高频 Resource

长时间产生大量 Update。

结果：

- Journal 不无限成为冷启动负担
- Checkpoint / Compaction 自动控制恢复成本
- 用户实时编辑不因后台维护明显卡顿

---

### 场景 11：多个 Resource 并发

多个 Resource 同时高频编辑并生成 Checkpoint。

结果：

- 可以并行处理
- 单个大型 Resource 不明显拖慢其他 Resource
- 不出现全局串行持久化瓶颈

---

### 场景 12：客户端拥有服务端未 Durable 的状态

服务端在极短持久化窗口内崩溃。

客户端仍保留该修改。

结果：

```text
服务端恢复 Durable State
↓
客户端重连
↓
Yjs State Vector
↓
客户端补回服务端缺失状态
```

---

## 42. 本地 AI 实现自由度

本设计不规定：

- 必须使用哪种数据库
- 必须使用哪种消息队列
- Journal 一定是一行一条还是 Segment
- Checkpoint 的具体二进制格式
- Worker 数量
- Compaction 的固定阈值
- 单 Resource 的锁实现
- Actor / Mutex / Transaction / Lease 的具体选择
- 客户端本地存储的具体库

本地 AI 可以根据现有项目技术栈、部署方式和压测结果选择实现。

但必须满足本设计的功能、边界和验收条件。

---

## 43. 架构硬约束

1. 持久化采用 `Durable Update Journal + Checkpoint + Compaction`。
2. Journal 是当前状态可靠恢复的主链，Checkpoint 是恢复加速和数据规模控制手段。
3. 用户输入不得等待 Journal、Checkpoint 或 Compaction。
4. 持久化窗口默认尽可能短，但具体毫秒数不在架构阶段写死。
5. Journal 可以短时间聚合 / 合并 Yjs Update，但不能明显扩大持久化窗口。
6. Checkpoint 必须对应明确的 Durable Journal Boundary。
7. 新 Checkpoint 验证完成以前，旧恢复链不能被破坏。
8. Compaction 必须先建立并验证新 Checkpoint，再回收旧 Journal。
9. Session 安全释放只要求必要 Update 已 Durable，不强制同步生成 Checkpoint。
10. Resource 冷启动使用 `Verified Checkpoint + 后续 Durable Journal` 恢复。
11. 客户端与服务端状态通过 Yjs State Vector 补齐，不进行整份覆盖。
12. 可编辑客户端应支持本地 Yjs 状态恢复。
13. Journal 暂时不可用时不得伪造 Durable，也不得无限积压。
14. 不同 Resource 的持久化、Checkpoint 和恢复应可以并行。
15. Awareness、Asset、History 与当前状态持久化必须保持职责分离。
16. Persistence Cursor 只用于恢复管理，不作为 CRDT 冲突版本号。
17. Persistence 与 History 可以复用底层数据，但不能被设计成同一个产品能力。
18. `Snapshot` 一词不用于本模块的持久化基准状态，统一使用 `Checkpoint`。
19. Resource Ownership 切换必须具备 stale-owner fencing；新 Owner 生效后，旧 Owner 不能继续推进权威 Runtime State 或 Durable Boundary。

---

## 44. 最终恢复模型

```text
                    ┌────────────────────┐
                    │ Client Local State │
                    └─────────┬──────────┘
                              │
                              │ State Vector / Update
                              ▼
┌──────────────┐      ┌───────────────────┐
│ Checkpoint N │ ───→ │ Resource Session  │
└──────────────┘      │      Y.Doc        │
        │             └─────────┬─────────┘
        │                       │
        │             Realtime │ Update
        │                       │
        ▼                       ▼
┌─────────────────────────────────────────┐
│ Durable Journal after Checkpoint N      │
└─────────────────────────────────────────┘
```

冷启动：

```text
Verified Checkpoint
+
Checkpoint 后 Durable Journal
↓
Server Y.Doc
+
Client Local State
↓
Yjs State Vector
↓
最终收敛
```

后台维护：

```text
Journal 增长
↓
满足恢复成本 / 数据规模条件
↓
生成 Checkpoint
↓
验证
↓
发布
↓
旧 Journal 进入 Compaction / Retention
```

实时编辑、可靠持久化和后台维护是三条协作但不互相阻塞的路径。
