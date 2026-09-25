# Realtime Collaboration Protocol Design

## 1. 目标

本设计定义系统统一的实时协作协议与 Session 生命周期。

目标不是规定某个 WebSocket 库、某个类或某段代码应该怎样实现，而是规定所有前端、后端和协作模块必须共同满足的行为。

核心目标：

- 一个统一协议服务所有 `Resource`
- 用户输入采用 local-first，不等待网络或持久化
- 多个 Resource 可以同时协作，彼此不能形成明显阻塞
- Yjs 负责 CRDT 同步，不重新实现字符级冲突协议
- Awareness 负责临时在线状态，不进入持久化正文
- 网络断开后可以继续本地编辑，并在恢复后自动收敛
- 慢客户端、高频 Presence、大型同步不能拖垮实时编辑
- Session 与具体 WebSocket 连接解耦
- 协议原生支持并发、多 Resource 和后续横向扩展

---

## 2. 已确定的上层约束

本协议建立在以下已经确定的规则上：

```text
Resource
= 系统唯一的实时协作边界

Yjs
= 统一 CRDT 协作内核

Document Resource
= ProseMirror / Tiptap + Yjs

NodeRef
= resourceId + nodeId

Presence
= Awareness

保存按钮
= 不存在
```

实时协议不得破坏这些既有规则。

---

## 3. 三个必须分开的概念

### 3.1 Connection

`Connection` 表示客户端和协作服务之间的物理实时连接。

第一阶段默认使用：

```text
WebSocket
```

它负责：

- 建立实时连接
- 认证上下文
- 心跳
- 消息运输
- 承载一个或多个 Resource 的实时消息

Connection 不是 Resource。

Connection 断开，也不表示 Resource 被删除或关闭。

---

### 3.2 Resource Session

`Resource Session` 表示某个 Resource 当前在服务端运行的实时协作空间。

一个 Resource 在任意时刻只对应一个逻辑上的共享协作状态。

Resource Session 负责：

- 当前 Resource 的 Y.Doc
- Awareness
- 当前参与者
- 实时同步
- Resource 级权限上下文
- 持久化管线
- Session 生命周期

Resource Session 不等于某一个用户的连接。

---

### 3.3 Subscription

`Subscription` 表示：

> 某个 Client 当前加入了某个 Resource Session。

一个 Connection 可以同时拥有多个 Subscription。

例如：

```text
Connection
├── Subscription → Resource A
├── Subscription → Resource B
└── Subscription → Resource C
```

关闭 Resource B 时，只退出 B。

A 和 C 不受影响。

---

## 4. 核心连接模型

默认采用：

```text
一个 Client
    │
    └── 一个长期 Connection
            │
            ├── Resource A
            ├── Resource B
            └── Resource C
```

但这不是“整个客户端永远只能有一个 WebSocket”的硬限制。

正式约束是：

> 一个 Transport Connection 可以多路复用多个 Resource Session，但 Resource Session 不依赖某个特定物理 Connection 存在。

系统允许在负载较高时建立：

```text
Transport Pool
├── Connection 1
│   ├── Resource A
│   └── Resource B
│
└── Connection 2
    └── Resource C
```

这样某个大型或高频 Resource 可以迁移到独立连接，不需要改变 Resource Session、Yjs 或上层业务模型。

---

## 5. Local-first 编辑原则

用户输入必须先作用于本地编辑状态。

正确路径：

```text
User Input
↓
Local Editor
↓
Local Y.Doc
↓
UI 立即更新
↓
后台发送 Yjs Update
```

禁止：

```text
User Input
↓
发送 Server
↓
等待 Server
↓
等待持久化
↓
Server 返回
↓
UI 才更新
```

网络、数据库、Checkpoint、History、Search Index、AI 等任何后台系统都不得进入用户输入的等待路径。

### 5.1 Local / Synced / Durable

实时协议必须允许系统区分：

```text
Local
Synced
Durable
```

`Local` 表示修改已进入客户端本地 Y.Doc。

`Synced` 表示修改已进入实时协作传播路径。

`Durable` 表示修改已进入可靠的持久化 Journal，即使当前 Resource Session 消失，也可以从持久化系统恢复。

三者不要求在同一时刻发生。

实时体验不能等待 Durable，但系统也不能把尚未 Durable 的状态伪装成已经安全保存。

---

## 6. 统一协议只负责运输和路由

实时协议不重新定义 CRDT 编辑语义。

正文同步继续使用 Yjs 标准能力。

推荐直接复用：

```text
y-protocols/sync
y-protocols/awareness
```

统一协议只在外层解决：

```text
这是什么消息
属于哪个 Resource
属于哪个 Subscription
如何路由
优先级是什么
是否允许丢弃
发生错误时影响哪个范围
```

不得重新设计：

```text
insertCharacter
deleteCharacter
mergeText
blockVersion
conflictResolver
```

作为网络协作协议。

---

## 7. 消息类别

实时协议至少分成四类消息。

### 7.1 Control

负责连接和 Resource 生命周期。

包括：

```text
connect
ready
subscribe
subscribed
unsubscribe
permission
schema
error
ping
pong
```

特点：

```text
可靠
低频
不能被 Awareness 消息阻塞
```

---

### 7.2 Sync

负责 Yjs 正文同步。

包括：

```text
initial sync
state vector
state diff
Yjs update
```

底层内容使用 Yjs Sync Protocol。

特点：

```text
可靠
不能静默丢弃
允许合并
必须最终收敛
```

正文每次输入不需要业务层单独设计 ACK。

但客户端必须能区分：

```text
Local
Synced
Durable
```

因此 Realtime Protocol 必须提供**批量状态边界**，而不是每个按键一个业务 ACK。

### 7.2.1 Sync / Durable Watermark

协议至少需要表达两个可证明的边界：

```text
acceptedWatermark
= 服务端当前 Resource Session 已接受并合并到权威 Y.Doc 的状态边界

durableWatermark
= 持久化层已经确认进入 Durable Journal 的状态边界
```

Watermark 是语义，不限定必须使用整数序号。实现可以使用：

```text
Yjs State Vector
Journal Cursor
opaque monotonic token
或等价可比较边界
```

要求：

- 可以批量 / 周期性发送，不要求逐字符 ACK。
- `WebSocket.send()` 成功不能推导出 `Synced` 或 `Durable`。
- `Synced` 必须有服务端 acceptance boundary 作为依据。
- `Durable` 必须有 Persistence 确认的 durable boundary 作为依据。
- Reconnect 后如果边界未知，客户端先回到 `Syncing`，通过 State Vector / Receipt 重新建立事实。
- Watermark 只描述同步 / 持久化覆盖范围，不成为 CRDT 冲突版本号。

---

### 7.3 Awareness

负责临时协作状态。

包括：

```text
online
cursor
selection
user state
editing state
```

特点：

```text
临时
不持久化
允许节流
允许合并
允许丢弃过期中间状态
只要求最终展示最新状态
```

例如：

```text
cursor 1
cursor 2
cursor 3
...
cursor 100
```

网络拥堵时没有必要全部发送。

可以只保留：

```text
cursor 100
```

---

### 7.4 System

用于服务健康和协议维护。

例如：

```text
server draining
resource moved
retry
rate limited
protocol incompatible
session closed
```

System 消息不得包含具体 Document 内容语义。

---

## 8. 消息外层统一结构

所有实时消息必须有统一的路由外层。

至少能够表达：

```text
protocolVersion
messageType
resourceId
subscriptionId
requestId（仅需要请求响应关联时）
payload
```

要求：

- `resourceId` 用于确定协作边界
- `subscriptionId` 用于区分一次具体加入关系
- `requestId` 只用于 Control 类需要明确响应的操作
- Sync / System Control 可以携带 acceptance / durable watermark 或等价 receipt；普通 Yjs Update 不要求每条都携带
- Yjs binary update 不得转成 Base64 JSON 再传输
- 二进制协作数据应保持二进制运输
- 不要求所有消息都包含无意义字段

具体编码格式由实现阶段选择，但不得破坏以上语义。

---

## 9. 身份规则

协议层必须区分：

```text
userId
clientId
resourceId
subscriptionId
```

含义：

### userId

认证后的用户身份。

必须来自服务端可信认证上下文。

不能信任客户端随消息提交的 userId。

### clientId

一次客户端实例的身份。

同一个用户：

```text
电脑浏览器
手机
另一个 Tab
```

可以拥有不同 clientId。

Presence 不能只依赖 userId 判断唯一客户端。

### resourceId

系统唯一协作边界。

### subscriptionId

一次 Client 加入 Resource 的短生命周期身份。

重新连接或重新 Subscribe 后可以生成新的 subscriptionId。

旧 Subscription 的延迟消息不能污染新的 Subscription。

---

## 10. Connection 生命周期

Connection 生命周期固定为：

```text
DISCONNECTED
↓
CONNECTING
↓
AUTH
↓
READY
↓
承载多个 Subscription
↓
DRAINING / DISCONNECTING
↓
DISCONNECTED
```

要求：

- 认证只建立 Connection 身份上下文
- Resource 权限仍然在 Subscribe 时单独检查
- 一个 Resource Subscribe 失败不能自动关闭整个 Connection
- Connection 断开后，其下所有 Subscription 进入重连流程
- Connection 恢复后，客户端重新 Subscribe 仍然需要的 Resource

---

## 11. Subscription 生命周期

每个 Resource 的加入关系独立运行。

生命周期：

```text
NONE
↓
SUBSCRIBING
↓
权限检查
↓
Protocol / Schema 检查
↓
SYNCING
↓
LIVE
↓
UNSUBSCRIBING
↓
NONE
```

可能的终止状态：

```text
PERMISSION_DENIED
RESOURCE_NOT_FOUND
SCHEMA_INCOMPATIBLE
PROTOCOL_INCOMPATIBLE
RESOURCE_DELETED
```

进入 `LIVE` 以前必须完成必要的兼容性检查和初始同步。

---

## 12. 初始同步

用户加入 Resource 时按以下逻辑执行：

```text
Subscribe(resourceId)
↓
检查 Resource 是否存在
↓
检查 read / edit 权限
↓
检查 protocolVersion
↓
检查 schemaVersion / Resource Type 兼容性
↓
加入 Resource Session
↓
执行 Yjs state vector 同步
↓
同步当前 Awareness
↓
进入 LIVE
```

初始同步不得要求下载完整 JSON 文档作为实时 Source of Truth。

优先使用 Yjs 的状态差异同步。

大型 Resource 的初始同步不能长期占用其他活跃 Resource 的实时通道。

必要时允许：

- 使用独立 Transport
- 分离大型同步流量
- 使用增量恢复
- 对大数据进行受控分段

具体策略由实现阶段根据压力测试确定。

---

## 13. 实时编辑

进入 `LIVE` 后：

```text
Local Edit
↓
Local Y.Doc
↓
Yjs Update
↓
Realtime Protocol
↓
Resource Session
↓
其他 Client
```

服务端不需要理解：

```text
paragraph
heading
table
codeBlock
```

这些属于 Resource Type 内部模型。

实时协作层只处理 Yjs Update。

---

## 14. Awareness 行为

Awareness 只属于当前 Resource Session。

不得跨 Resource 共享。

例如用户同时打开：

```text
main.ts
design.md
```

两个 Resource 的：

```text
cursor
selection
editing state
```

必须分别维护。

Awareness 不进入：

```text
Checkpoint
History
Document Content
数据库正文
```

正常退出 Resource 时立即移除相应 Presence。

异常断线时通过：

```text
Connection liveness
+
Awareness timeout
```

清理失效 Presence。

---

## 15. 消息优先级

不能让所有消息进入一个简单 FIFO 队列。

至少需要区分：

```text
Priority 1
Control

Priority 2
Yjs Sync / Update

Priority 3
Awareness
```

后台任务：

```text
Checkpoint
History
Search Index
AI Context Build
Asset
大型 Export / Import
```

不得与实时编辑共享同一个无差别发送队列。

---

## 16. Resource 独立队列

每个 Resource 必须拥有独立的逻辑发送与处理队列。

禁止：

```text
Global Queue

A1
A2
A3
A4
B1
C1
```

导致 A 长时间占用整个实时连接。

要求：

```text
Resource A Queue
Resource B Queue
Resource C Queue
```

Transport 对多个 Resource 进行公平调度。

具体调度算法由实现阶段选择。

架构只要求：

> 一个高流量 Resource 不得长期占满整个 Connection，使其他 Resource 明显失去实时性。

---

## 17. 同一个 Resource 的并发原则

系统要求多 Resource 并行，但不要求对同一个 Y.Doc 进行不受控制的多线程并行写入。

正确原则：

```text
不同 Resource
→ 可以并行处理

同一个 Resource
→ 可以并发接收多个 Client 的操作
→ 由一个安全的逻辑更新路径应用到同一个 Y.Doc
→ Yjs 负责 CRDT 收敛
```

不要为了追求“并行”而让多个线程无约束地同时修改同一个 Y.Doc。

这不属于性能优化，而会制造数据竞争。

---

## 18. Backpressure

实时系统必须原生支持 Backpressure。

不得让慢客户端无限积压消息。

对于 Awareness：

```text
旧状态
→ 可以直接丢弃

只保留最新状态
```

对于 Yjs Update：

```text
不能静默丢弃
```

当单个客户端明显落后时，允许：

```text
合并多个 Yjs Update
↓
仍然落后
↓
停止无限堆积历史增量
↓
重新执行状态差异同步
```

目标：

> 慢客户端只能影响自己，不能持续消耗无限服务端内存，也不能拖慢同一 Resource 的其他正常客户端。

---

## 19. Update 合并

Yjs Update 可以根据负载进行合并，以降低消息数量。

允许：

```text
Update A
Update B
Update C
↓
Merged Update
```

但必须满足：

- 不能改变最终 CRDT 状态
- 不能为了合并而明显增加正常编辑延迟
- 不能静默丢失正文修改
- 合并策略必须有大小和时间上限

具体阈值由性能测试决定，不写死在架构设计中。

---

## 20. Presence 节流

高频 Presence 默认允许节流。

例如：

```text
cursor move
selection change
pointer move
```

不要求每一个中间状态都通过网络发送。

原则：

```text
正文修改
优先保证可靠和实时

Presence
优先保证最新
```

不能反过来。

---

## 21. 大消息隔离

以下数据不得直接占用实时编辑热路径：

```text
大型 Asset
完整 History
大型 Export
大型 Import
Search Index
AI 大上下文
完整 Checkpoint 下载
```

如果某个 Resource 的初始同步本身非常大，也需要进入大消息保护机制。

系统必须具备以下至少一种能力：

```text
独立 Transport
专用大数据通道
受控分段
后台加载
```

具体实现可以变化。

目标不变：

> 大消息不能让另一个正在输入文字的 Resource 出现明显卡顿。

---

## 22. Transport Pool

默认可以复用一个 Connection。

但协议必须支持：

```text
Transport Pool
```

当出现以下情况时：

- 某个 Resource 长时间高流量
- 大型初始同步
- 单连接持续 Backpressure
- 多个活跃 Resource 同时产生大量数据

系统可以把某个 Subscription 分配到另一个 Connection。

Resource Session 不得依赖固定 Socket，因此迁移后只需要重新同步状态，不需要改变 Resource 模型。

---

## 23. TCP 队头阻塞边界

WebSocket 第一阶段通常建立在 TCP 上。

因此即使应用层存在独立队列，单个 TCP Connection 仍然可能发生传输层队头阻塞。

本架构不假设应用层调度可以完全消除这一问题。

因此：

- 不把“永远单 WebSocket”设为架构约束
- 支持 Transport Pool
- 支持大型 Resource 独立连接
- Session 与 Transport 解耦

未来如果迁移到支持独立 Stream 的 Transport，Resource Session 和上层协议不应被推翻。

---

## 24. 断线继续编辑

网络暂时中断时：

```text
Connection
→ disconnected
```

但本地编辑器不得停止工作。

正确行为：

```text
用户继续编辑
↓
Local Y.Doc 继续变化
↓
保留尚未同步的本地状态
```

UI 应明确区分：

```text
正在编辑
已离线
正在重新连接
同步完成
```

但不能用阻塞弹窗打断正常输入。

---

## 25. 客户端本地恢复

为了避免：

```text
离线编辑
+
页面刷新 / 浏览器崩溃
→ 未同步内容全部消失
```

客户端应具备 Yjs 本地状态恢复能力。

至少需要保证未同步的本地内容不会因为普通重连而被覆盖。

是否使用 IndexedDB 或其他具体技术由客户端实现决定。

架构要求是：

> 本地未同步修改必须被视为有效协作状态，不能在重连时简单用服务端内容覆盖。

---

## 26. 重连流程

Connection 恢复以后：

```text
重新认证
↓
重新 Subscribe 当前仍需要的 Resource
↓
重新检查权限
↓
重新检查兼容性
↓
使用 Yjs state vector 比较双方状态
↓
双向补齐缺失 Update
↓
重新发布当前 Awareness
↓
回到 LIVE
```

禁止：

```text
Reconnect
↓
Server 整份 Document 覆盖 Client
```

也禁止：

```text
Client 整份 Document 无条件覆盖 Server
```

最终状态由 Yjs 同步协议收敛。

---

## 27. Awareness 重连

Awareness 是临时状态。

断线期间积累的：

```text
旧 cursor
旧 selection
旧 online state
```

不需要重放。

重连后只发送客户端当前最新 Awareness。

---

## 28. 权限检查

Connection 认证成功，不代表拥有所有 Resource 权限。

每次 Subscribe 都必须检查 Resource 权限。

至少支持：

```text
read
edit
```

read 用户：

- 可以接收 Sync
- 可以按策略参与 Awareness
- 不能提交有效正文 Update

edit 用户：

- 可以接收和发送正文 Update

服务端不能只信任客户端 UI 是否禁用了编辑按钮。

收到正文 Update 时仍必须确保当前 Subscription 具备 edit 权限。

---

## 29. 权限实时变化

Resource 权限可能在 Session 存活期间变化。

例如：

```text
edit
↓
read
```

服务端必须能够立即：

```text
停止接受该 Client 的新正文 Update
↓
通知 Client 权限变化
```

如果用户离线期间已经产生本地修改，而重连时发现失去 edit 权限：

```text
这些本地修改不能写入共享 Resource
```

但也不能静默删除。

客户端应保留这些修改，并允许后续：

- 权限恢复后重新同步
- 复制内容
- 导出本地修改

具体 UI 由产品层决定。

---

## 30. Schema 与协议兼容

连接级使用：

```text
protocolVersion
```

Resource 级使用：

```text
schemaVersion
resourceType
```

进入编辑以前必须检查兼容性。

如果旧客户端无法安全理解新 Schema：

```text
不得进入正常 edit 状态
```

可以根据产品策略：

```text
拒绝加入
或
降级为只读
```

不得让旧客户端通过 ProseMirror normalization 等行为破坏未知 Node。

---

## 31. Error Scope

错误必须按最小影响范围处理。

### Message Error

只影响当前消息。

### Subscription Error

只影响当前 Resource。

例如：

```text
permission denied
resource not found
schema incompatible
```

不能让 Resource A 的错误关闭 Resource B、C。

### Connection Error

只有以下类型才影响整个 Connection：

```text
认证失败
Transport 损坏
严重协议错误
连接关闭
```

---

## 32. 心跳与失活检测

Connection 必须有 liveness 机制。

目的：

- 发现异常断开的 Client
- 清理失效 Subscription
- 清理 Awareness
- 防止服务端长期保留僵尸连接

具体心跳间隔由部署环境决定。

不得把高频 Cursor 更新当作唯一心跳依据。

---

## 33. Resource Session 服务端生命周期

Resource Session 生命周期：

```text
COLD
↓
LOADING
↓
ACTIVE
↓
IDLE
↓
EVICTED
```

### COLD

Resource 当前没有加载到实时协作运行时。

### LOADING

第一次需要时从持久化状态恢复。

同一个 Resource 并发进入时，不应被重复加载成彼此隔离的多个本地状态。

### ACTIVE

存在在线 Subscription，或仍有必要的实时处理任务。

### IDLE

没有在线用户，但可以短时间保留为热缓存。

### EVICTED

安全释放：

```text
Y.Doc
Awareness
内存索引
临时队列
```

但不会删除 Resource 本身。

---

## 34. Session 释放条件

Resource Session 不能因为：

```text
最后一个用户刚刚离开
```

就立即无条件销毁。

释放前至少保证：

- 没有活跃 Subscription
- 当前服务端已接收并需要保存的正文 Update 已进入 Durable Update Journal
- 没有必须完成的恢复任务
- Awareness 已清理
- 不存在未处理的关键 Sync 消息

Session 回收不要求同步生成新的 Checkpoint。

只要必要 Update 已 Durable，Checkpoint 可以由后台任务稍后生成。

可以保留短 TTL 热缓存。

具体 TTL 由部署和性能测试决定。

---

## 35. Session 冷启动

第一个用户进入一个未加载 Resource 时：

```text
Subscribe
↓
Resource Session LOADING
↓
加载 Latest Verified Checkpoint
↓
重放 Checkpoint 之后的 Durable Journal
↓
恢复服务端 Y.Doc
↓
建立 Awareness
↓
完成必要校验
↓
ACTIVE
↓
Initial Sync
```

多个用户同时进入同一个冷 Resource 时：

```text
共享同一次逻辑加载结果
```

不能各自加载出互不相知的 Session。

---

## 36. 服务端集群要求

未来存在多个协作服务实例时：

```text
Gateway A
Gateway B
Gateway C
```

无论用户连接到哪个实例，同一个 Resource 的参与者必须属于同一个逻辑 Resource Session。

实现可以选择：

- Resource Owner / Shard
- Cluster Routing
- Distributed Sync Bus
- 其他可靠方案

本设计不绑定具体中间件。

但禁止出现：

```text
User A → Server 1 → Resource X 副本 1

User B → Server 2 → Resource X 副本 2

两个副本互相不知道对方存在
```

Resource 可以按 `resourceId` 横向分片。

不能让所有 Resource 最终又汇聚到一个全局单点串行处理器。

---

## 37. 服务故障与恢复

某个协作服务实例异常退出时：

- Resource 本身不能丢失
- 客户端进入重连
- 新实例可以从持久化状态恢复 Resource Session
- 客户端通过 Yjs state vector 补齐服务端尚未拥有的状态
- Awareness 重新建立，不恢复过期 Presence

Yjs CRDT 的可重放和幂等特性应被利用，不额外建立传统版本冲突系统。

---

## 38. 持久化边界

本协议只规定实时层与持久化层的边界。

正文 Update 必须尽快进入：

```text
Durable Update Journal
```

但 Journal 写入、Checkpoint、Compaction 都不得进入用户本地输入等待路径。

持久化采用：

```text
Hot State
+
Durable Update Journal
+
Checkpoint
+
Compaction
```

其中：

```text
Journal
= 当前状态可靠恢复主链

Checkpoint
= 缩短恢复路径和控制数据规模

Compaction
= 在安全 Checkpoint 基础上回收旧恢复负担
```

以下重工作不得阻塞实时编辑：

```text
Checkpoint
Compaction
History Diff
Search Index
AI Index
```

客户端本地状态与服务端恢复后的 Y.Doc 通过 Yjs State Vector 补齐差异，不使用整份覆盖。

详细规则由 `Persistence Design` 定义。

---

## 39. History 边界

History 不属于实时传输主通道。

实时层只负责：

```text
当前共享状态收敛
```

History 负责：

```text
版本查看
版本恢复
Diff
审计
```

不得为了 History 给每个实时字符操作增加传统：

```text
version++
```

冲突控制。

---

## 40. 安全要求

实时协议至少必须满足：

- 不信任客户端提交的 userId
- Subscribe 必须校验 Resource 权限
- Update 必须确认当前 Subscription 有 edit 权限
- Client 不能向未 Subscribe 的 resourceId 任意发送正文 Update
- 对消息大小设置合理上限
- 对异常高频消息进行限流
- Awareness 与正文 Update 使用不同的限流策略
- 非法消息不能导致整个协作服务崩溃
- 服务端不能把内部异常堆栈直接广播给其他用户

具体认证技术不在本模块决定。

---

## 41. 资源保护

为了避免一个异常客户端拖垮系统，服务端必须能够限制：

```text
单 Connection 队列大小
单 Subscription 队列大小
单 Resource 内存占用
单消息大小
Awareness 发送频率
持续异常 Update
```

超过安全边界时：

- Awareness 优先丢弃旧状态
- Yjs Update 不得静默丢失
- 可以要求重新同步
- 可以隔离单个 Subscription
- 严重异常可以关闭对应 Connection

不能通过无限内存缓存“解决”慢客户端。

---

## 42. 可观测性

协作层必须能观察至少以下指标：

```text
active connections
active resource sessions
subscriptions per resource
sync bytes
awareness bytes
queue size
backpressure count
dropped awareness count
reconnect count
initial sync duration
remote update latency
session load duration
session idle / eviction count
protocol / schema rejection count
```

没有这些指标，就无法判断“用户无感”是否真的成立。

具体阈值由真实压力测试确定。

---

## 43. 命名要求

协议与模块使用简单、稳定的英文名称。

推荐：

```text
Connection
Resource
Session
Subscription
Sync
Update
Awareness
Presence
Cursor
Selection
Subscribe
Unsubscribe
Permission
Schema
Error
Retry
```

避免：

```text
RealtimeCollaborativeResourceOrchestrator
PresenceReconciliationCoordinator
ConcurrentMutationSynchronizationManager
```

名称应方便非英语母语开发者理解。

---

## 44. 禁止设计

不得出现：

```text
一个 Resource 一个固定 WebSocket
```

作为不可改变的架构规则。

不得出现：

```text
所有 Resource
→ 一个全局 FIFO Queue
```

不得让：

```text
Cursor / Presence
```

堵住正文 Update。

不得让：

```text
大型 Checkpoint / Asset / AI Context
```

进入实时编辑热路径。

不得在网络恢复时：

```text
Server JSON 覆盖 Client
```

或：

```text
Client JSON 覆盖 Server
```

不得为实时编辑重新加入：

```text
Save
baseVersion
blockVersion
手动字符冲突算法
```

不得让 Resource A 的协议错误默认关闭 Resource B。

不得无限积压慢客户端消息。

---

## 45. 核心验收场景

### 场景 1：基础多人编辑

```text
User A + User B
打开同一个 Document
↓
同时输入
↓
双方近实时看到修改
↓
最终 Y.Doc 一致
```

---

### 场景 2：同一用户多个 Resource

```text
main.ts
README.md
design.md
```

同时打开。

三个 Resource 各自同步、Presence 独立、互不覆盖。

---

### 场景 3：一个 Resource 高频修改

Resource A 高频输入时：

```text
Resource B
```

仍然可以正常实时编辑。

不能因为 A 的队列很长而让 B 长时间无响应。

---

### 场景 4：Cursor Flood

某 Client 高频移动 Cursor。

结果：

- 旧 Cursor 状态允许丢弃
- 最新 Cursor 正常到达
- 正文 Yjs Update 不被 Cursor 队列拖住

---

### 场景 5：慢客户端

一个 Client 网络极慢。

结果：

- 服务端内存不能无限增长
- 正常 Client 不受明显影响
- Awareness 自动压缩到最新状态
- Yjs Update 可以合并或触发重新同步

---

### 场景 6：断网继续编辑

用户断网后继续输入。

结果：

```text
本地输入正常
↓
内容不丢失
↓
网络恢复
↓
重新 Subscribe
↓
Yjs 双向补齐
↓
最终收敛
```

---

### 场景 7：断网期间双方同时修改

A 离线修改。

B 在线继续修改同一个 Resource。

A 恢复网络后：

```text
不能整份覆盖
不能要求用户手动保存
```

由 Yjs 自动合并并最终收敛。

---

### 场景 8：权限被撤销

用户原本：

```text
edit
```

运行中变成：

```text
read
```

结果：

- 继续接收允许的实时更新
- 新正文修改不再被服务器接受
- 本地未同步修改不能静默丢失

---

### 场景 9：Schema 不兼容

旧 Client 打开新 Schema Resource。

结果：

- 不得进入正常可编辑状态
- 不得因为旧 Schema normalization 破坏未知内容
- 根据策略拒绝或只读

---

### 场景 10：服务端重启

协作服务重启以后：

```text
Resource Session 重新加载
↓
Client 重连
↓
state vector 同步
↓
恢复 LIVE
```

Resource 内容保持正确。

---

### 场景 11：Session 回收

最后一个用户离开。

结果：

```text
Session → IDLE
↓
完成必要持久化
↓
达到回收条件
↓
释放运行时内存
```

Resource 本身继续存在。

---

### 场景 12：大型初始同步

Resource A 很大并正在首次加载。

同时 Resource B 正在正常编辑。

结果：

> Resource A 的大型同步不能让 Resource B 的输入和小型实时更新明显停顿。

---

### 场景 13：多 Tab

同一 userId 打开两个浏览器 Tab。

结果：

- 可以存在两个不同 clientId
- Awareness 不互相覆盖
- UI 可以选择把两个 Client 聚合为同一个用户展示
- 协议层仍保留 Client 级身份

---

### 场景 14：错误隔离

Resource A 收到无效消息。

结果：

```text
A Subscription 可以报错或关闭
```

但：

```text
Resource B
Resource C
```

继续正常工作。

---

## 46. 性能验收原则

本设计不在架构阶段写死固定毫秒值。

但测试必须证明：

- 本地输入不等待网络
- 正常网络下远端修改接近实时
- Presence 高频变化不会影响正文同步
- 单 Resource 高负载不会明显拖慢其他 Resource
- 慢客户端不会产生无限队列
- 断线重连不需要整份覆盖
- 大型同步和后台任务不会进入输入关键路径
- 多 Resource 可以被并发处理
- 系统压力增加时优先降低 Presence 精度，而不是丢失正文修改

正式性能阈值在实现后根据目标设备、部署环境和压力测试确定。

---

## 47. 与其他模块的边界

### Resource Design

负责：

```text
什么是 Resource
resourceId
Resource Type
```

### Block / Node Identity Design

负责：

```text
Document 内部 Node
nodeId
NodeRef
RelativePosition
```

### Realtime Collaboration Protocol

负责：

```text
Connection
Subscription
Sync
Awareness
Backpressure
Reconnect
Session Lifecycle
```

### Persistence Design

负责：

```text
Durable Update Journal
Checkpoint
Compaction
客户端本地恢复边界
Session 安全释放条件
故障恢复
```

### History Design

负责：

```text
Version History
Diff
Restore
Audit
```

### Permission Design

负责：

```text
权限模型
授权来源
共享策略
```

实时协议只消费权限结果，不自行发明第二套权限系统。

---

## 48. 架构硬约束

以下规则作为本模块最终约束：

1. `Connection` 与 `Resource Session` 必须分离。
2. 一个 Connection 可以承载多个 Resource Subscription。
3. 不允许把所有 Resource 永久绑定到单一 WebSocket。
4. 系统必须支持 Transport Pool 或等价的流量隔离能力。
5. 用户编辑必须 local-first，网络和持久化不能阻塞本地输入。
6. 正文同步使用 Yjs Sync Protocol，不重新实现字符冲突算法。
7. Awareness 是临时状态，允许节流、合并和丢弃旧状态。
8. Yjs Update 不能静默丢弃。
9. 不同 Resource 必须有独立逻辑队列并公平调度。
10. 一个高流量 Resource 不能长期堵塞其他 Resource。
11. 慢客户端不能产生无限消息积压。
12. 网络恢复后使用 Yjs state vector 重新同步，不进行整份覆盖。
13. Resource 权限在 Subscribe 和正文 Update 时都必须有效。
14. Schema 不兼容的 Client 不能进入不安全的 edit 状态。
15. Resource Session 按需加载，并在安全条件满足后释放。
16. 不同 Resource 可以并行处理；同一个 Y.Doc 不进行无约束并行写入。
17. 大型同步、Checkpoint、History、Asset、AI 等不能占用实时编辑热路径。
18. Resource 级错误不得默认影响同一 Connection 上的其他 Resource。
19. 同一个 Resource 在集群中必须表现为一个逻辑协作空间。
20. 实时层必须区分 Local、Synced、Durable，不能把同步成功等同于可靠落盘。
21. Session 安全释放要求必要正文 Update 已进入 Durable Journal，不强制同步生成 Checkpoint。
22. Resource 冷启动使用 Verified Checkpoint + 后续 Durable Journal 恢复，再与客户端通过 State Vector 补齐。
23. 协议、字段和模块名称使用简单、稳定的英文。

---

## 49. 最终模型

```text
Client
│
├── Local Editor
│      ↓
│   Local Y.Doc
│      │
│      └── local-first
│
└── Transport Pool
       │
       ├── Connection A
       │      │
       │      ├── Subscription → Resource 1
       │      └── Subscription → Resource 2
       │
       └── Connection B
              │
              └── Subscription → Resource 3

Server
│
├── Collaboration Gateway
│
├── Resource Session 1
│      ├── Y.Doc
│      ├── Awareness
│      ├── Subscriptions
│      ├── Resource Queue
│      └── Persistence Pipeline
│
├── Resource Session 2
│      ├── Y.Doc
│      ├── Awareness
│      ├── Subscriptions
│      ├── Resource Queue
│      └── Persistence Pipeline
│
└── Resource Session 3
       ├── Y.Doc
       ├── Awareness
       ├── Subscriptions
       ├── Resource Queue
       └── Persistence Pipeline
```

实时主路径：

```text
User Input
↓
Local Editor
↓
Local Y.Doc
↓
Yjs Update
↓
Resource Queue
↓
Transport
↓
Resource Session
↓
Remote Client
```

临时状态：

```text
Awareness
↓
节流 / 合并 / 丢弃旧状态
↓
只传播最新有效 Presence
```

后台路径：

```text
Yjs Update
↓
Persistence

Checkpoint / Compaction / History / Search / AI
↓
Background Work
```

三条路径不得重新混成一个阻塞链。

---

## 50. 与统一模块通信协议的关系

本协议只负责系统统一通信体系中的实时 `Stream` 子协议。

系统所有模块之间的：

```text
Command
Query
Event
Async Task
Error
Retry
Idempotency
Trace
Contract Version
```

统一由：

```text
Unified Module Communication Design
```

定义。

本协议继续专注：

```text
Connection
Subscription
Resource Session
Yjs Sync
Awareness
Backpressure
Reconnect
Realtime Transport
```

不得为了“统一通信”把 Yjs 二进制同步重新包装成普通业务 JSON 消息。
