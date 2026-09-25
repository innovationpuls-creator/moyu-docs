# Deployment, Scaling & Disaster Recovery Design

## 1. 目标

本设计定义系统的生产部署、水平扩缩容、高可用、数据库拓扑、Resource 分片、滚动发布、备份、故障切换和灾难恢复能力。

本模块解决：

> 当系统从单机开发环境进入真实生产环境以后，如何让 Realtime、Persistence、Permission、Search、Asset、AI、Import / Export 等模块能够多实例运行，如何避免单点故障，如何在服务、数据库、节点、机房或存储发生异常时继续运行或快速恢复，并确保数据不会因为扩容或灾难恢复被破坏。

本项目主数据库确定使用：

```text
PostgreSQL
```

PostgreSQL 负责核心关系数据和需要事务一致性的系统状态。

本设计按可上线产品标准设计。

---

## 2. 总体部署模型

生产环境采用：

```text
Client
  │
  ▼
Edge / Load Balancer
  │
  ├── API Service
  ├── Realtime Gateway
  └── Download / Upload Entry
         │
         ▼
Application Services
  │
  ├── Resource
  ├── Permission
  ├── History
  ├── Search
  ├── Asset
  ├── AI
  ├── Import / Export
  └── Operations
         │
         ├── PostgreSQL
         ├── Object Storage
         ├── Search Engine
         ├── Queue / Event Bus
         ├── Cache
         └── External Providers
```

所有可横向扩展服务默认设计为：

```text
Stateless or Recoverable Stateful Service
```

不能因为某个服务实例退出，就永久丢失业务状态。

---

## 3. 服务分类

系统服务分为三类：

### Stateless Service

例如：

```text
HTTP API
Permission Query
Search API
Resource Metadata API
Import / Export API
```

特点：

- 可以多实例
- 不依赖本地长期状态
- 任意实例可以处理请求

### Session / Stateful Runtime Service

例如：

```text
Realtime Resource Session
Active Y.Doc Runtime
Long-lived WebSocket
```

特点：

- 运行期间存在内存状态
- 但状态必须能够从持久化恢复
- 单实例退出不能造成 Resource 永久丢失

### Worker Service

例如：

```text
AI Worker
Index Worker
Asset Processing Worker
Import / Export Worker
Checkpoint Worker
Purge Worker
Reconciliation Worker
```

特点：

- 异步
- 可重试
- 可水平扩展
- 任务状态持久化

---

## 4. PostgreSQL 的系统定位

PostgreSQL 作为系统主数据库。

主要保存：

```text
Workspace
Project
Folder
Resource Metadata
Permission
Membership
Share
Invitation
Lifecycle State
Task State
ChangeSet Metadata
History Metadata
Audit Metadata
Asset Metadata
Import / Export State
Operation State
Search Coordination Metadata
Configuration Metadata
```

根据最终 Persistence 实现，也可以承载：

```text
Durable Yjs Update Journal
Checkpoint Metadata
```

但大型二进制文件不得存入 PostgreSQL。

---

## 5. PostgreSQL 不负责的内容

以下数据不应直接塞入 PostgreSQL 大字段长期保存：

```text
视频
图片
大型附件
Export ZIP
Import 原文件
大型 Preview
媒体转码结果
```

这些进入：

```text
Object Storage
```

Search 倒排索引进入：

```text
Search Engine
```

向量数据可以进入：

```text
Vector Index / Search Engine
```

正式 Search / Vector Infrastructure 由 `26-Technology-Stack-Decision.md` 固定为 `OpenSearch 3.x`。

---

## 6. PostgreSQL 主从拓扑

生产至少采用：

```text
Primary
+
Replica
```

模型。

Primary 负责：

```text
所有权威写入
```

Replica 负责：

```text
只读查询
备份辅助
故障恢复
```

不能设计成：

```text
唯一一台 PostgreSQL
```

作为长期生产形态。

---

## 7. PostgreSQL 高可用

生产 PostgreSQL 必须具备：

```text
自动故障检测
Primary Failover
Replica Promotion
Connection Reconnect
WAL Replication
Backup
Point-in-Time Recovery
```

具体可以使用：

```text
Cloud Managed PostgreSQL
Patroni
Cloud HA
Operator
```

等成熟方案。

本项目不自研 PostgreSQL HA。

---

## 8. Primary Failure

Primary 故障时：

```text
Detect Failure
↓
Promote Replica
↓
Update Connection Routing
↓
Application Reconnect
↓
Resume Writes
```

应用服务必须能够处理：

```text
短暂连接失败
transaction retry
connection reset
```

不能因为数据库切主：

```text
要求手工重启所有应用服务
```

---

## 9. PostgreSQL Connection Pool

所有服务访问 PostgreSQL 必须使用：

```text
Connection Pool
```

生产环境建议配合：

```text
PgBouncer
```

或等价连接代理。

原因：

```text
大量 API / Worker 实例
不能每个实例直接创建大量数据库连接
```

需要限制全局连接数。

---

## 10. Connection Pool 保护

必须监控：

```text
active connection
idle connection
wait time
pool saturation
connection error
```

数据库连接池耗尽必须产生告警。

不能让：

```text
AI Worker
```

因为高并发任务耗尽数据库连接，进而拖垮 Realtime 和 Permission。

---

## 11. 读写分离

不是所有读都必须走 Replica。

必须区分：

### 必须读 Primary

```text
刚写入后的强一致读取
Permission Critical Check
Owner State
Lifecycle Critical State
Operation Coordination
```

### 可以读 Replica

```text
部分后台报表
非实时统计
较弱一致 Metadata Query
```

不能为了“读写分离”导致权限或状态读取过期。

---

## 12. Replica Lag

必须监控：

```text
Replication Lag
```

当 Replica Lag 超出安全范围：

```text
关键读取回到 Primary
```

不能继续使用明显过期 Replica 执行安全判断。

---

## 13. PostgreSQL Schema Migration

数据库 Schema Migration 必须：

```text
Backward Compatible First
↓
Deploy Code
↓
Backfill
↓
Switch Read / Write
↓
Remove Old Schema
```

避免一次发布直接执行：

```text
破坏性 ALTER
```

导致旧实例同时崩溃。

---

## 14. Expand / Contract

推荐 Schema Migration 使用：

```text
Expand
↓
Migrate
↓
Contract
```

例如字段替换：

```text
新增新字段
↓
双读 / 双写或兼容写
↓
Backfill
↓
切换
↓
删除旧字段
```

正式 PostgreSQL Migration Tool 使用 `Alembic`；Resource / Yjs Schema Migration 仍是独立迁移体系，不进入 Alembic。

---

## 15. PostgreSQL 大表设计

大型表必须从一开始考虑：

```text
Index
Partition
Retention
Vacuum
Bloat
Query Pattern
```

重点表包括：

```text
Yjs Update Journal
Audit
Event Outbox
Task
History
Activity
```

不能等几亿行后再临时设计生命周期。

---

## 16. Journal Partition

如果 Durable Yjs Journal 存入 PostgreSQL：

建议按：

```text
time
或
resource hash + time
```

进行 Partition。

目标：

- 控制单表规模
- 支持 Retention
- 支持 Compaction
- 降低 Vacuum 压力

具体 Partition Strategy 由压测决定。

---

## 17. Outbox

关键业务写入与 Event Publish 使用：

```text
Transactional Outbox
```

或等价可靠机制。

PostgreSQL Transaction 内：

```text
Business State
+
Outbox Event
```

一起提交。

随后由：

```text
Outbox Publisher
```

可靠发送到 Event Bus。

---

## 18. Outbox Scaling

Outbox Publisher 必须支持：

```text
multiple workers
batch
retry
dedup
lag monitoring
```

不能单线程成为系统全局瓶颈。

---

## 19. Stateless API Scaling

API Service 使用：

```text
Horizontal Scaling
```

负载均衡后：

```text
任何实例
```

都可处理普通 HTTP 请求。

不能依赖：

```text
本机 Session
本地登录状态
本地唯一 Cache
```

保证正确性。

---

## 20. Session State

用户登录 Session / Auth State 必须：

```text
可共享
可验证
可失效
```

不能只存在某一 API 实例内存。

具体 Auth 在后续 Account / Auth Design 中细化。

---

## 21. Realtime Gateway Scaling

Realtime Gateway 负责：

```text
WebSocket
Subscription
Connection
Transport
```

必须支持多实例。

Load Balancer 将不同客户端连接分配到多个 Gateway。

---

## 22. WebSocket Sticky Session

可以使用：

```text
Connection Stickiness
```

提高连接稳定性。

但系统正确性不能依赖：

```text
永远连接同一 Gateway
```

客户端重连到其他实例后：

```text
必须能够重新建立 Subscription
```

---

## 23. Resource Session Scaling

Resource Session 使用：

```text
resourceId
```

作为分片和路由核心。

同一个 Resource 的实时协作必须形成：

```text
一个逻辑 Collaboration Space
```

不能因为连接到了不同服务器就分裂成两个互不通信的 Y.Doc。

---

## 24. Resource Sharding

生产环境采用：

```text
resourceId → shard
```

的确定性分片策略。

可以使用：

```text
consistent hashing
rendezvous hashing
routing table
```

或等价方式。

具体算法由实现决定。

---

## 25. Shard 的目的

Resource Sharding 负责：

```text
把不同 Resource 分散到不同 Session Worker
```

例如：

```text
Resource A → Worker 1
Resource B → Worker 2
Resource C → Worker 3
```

这样不同 Resource 可以并行处理。

---

## 26. 同 Resource 的逻辑串行

同一个 Resource 内：

```text
并发客户端
```

可以同时产生 Yjs Update。

但一个 Active Y.Doc 的服务端状态修改必须经过：

```text
安全逻辑执行路径
```

避免多个线程 / Worker 无协调地写同一个 Runtime State。

这是：

```text
per Resource coordination
```

不是：

```text
global serialization
```

### 26.1 Resource Ownership Fencing

Resource Session 发生 Worker 切换、Shard 迁移或故障接管时，必须使用 ownership generation / epoch / fencing authority 或等价机制。

```text
Old Owner epoch N
New Owner epoch N+1
```

一旦 `N+1` 生效，`N` 即使由于网络分区恢复、暂停恢复或延迟消息继续运行，也不能继续推进该 Resource 的权威 Runtime State 或 Durable Boundary。Sticky Routing、Lease Timeout 或“正常情况下只有一个 Worker”都不能单独替代 fencing 安全性。

---

## 27. Hot Resource

单个 Resource 可能拥有：

```text
大量协作者
大量 update
大量 bandwidth
```

形成 Hot Resource。

系统必须能检测并隔离。

可以：

```text
独占 Worker
独立 Transport
提高资源配额
限制异常客户端
```

不能让一个热门文档拖慢整个集群。

---

## 28. Resource Session Placement

Session Placement 应考虑：

```text
worker load
memory
active connection
resource hotspot
region
```

不能只按：

```text
resourceId hash
```

永远机械固定到一台超载节点。

可使用：

```text
deterministic base placement
+
load-aware override
```

或等价方案。

---

## 29. Session Recovery

Realtime Worker 崩溃后：

```text
Resource Session
```

可以在其他 Worker 重新创建。

恢复流程：

```text
Latest Verified Checkpoint
+
Durable Journal
↓
Server Y.Doc
↓
Client Reconnect
↓
State Vector Diff
```

不能依赖旧 Worker 内存。

---

## 30. Session Drain

Worker 滚动发布或下线前：

```text
Stop New Sessions
↓
Mark Draining
↓
Allow Existing Sessions Finish / Migrate
↓
Ensure Durable State
↓
Close / Redirect
↓
Shutdown
```

不能直接：

```text
kill -9
```

所有连接。

---

## 31. Reconnect Strategy

客户端重连使用：

```text
exponential backoff
+
jitter
```

避免集群恢复时：

```text
所有 Client 同时重连
```

形成 Reconnect Storm。

---

## 32. Queue / Worker Scaling

所有异步 Worker：

```text
AI
Search Index
Asset Processing
Import / Export
History
Purge
Reconciliation
```

根据：

```text
queue depth
oldest task age
worker utilization
```

水平扩缩容。

---

## 33. 不同 Worker Pool 隔离

不同任务类型必须有独立并发控制。

例如：

```text
AI Worker Pool
Asset Worker Pool
Index Worker Pool
Import Worker Pool
```

不能让：

```text
一次超大 Project Import
```

吃光所有异步 Worker。

---

## 34. Priority

任务至少分：

```text
interactive
normal
background
maintenance
```

例如：

```text
用户等待的 AI Task
```

优先级高于：

```text
历史 Reindex
```

但不能让 Background 永久饿死。

---

## 35. Autoscaling

可以根据：

```text
CPU
Memory
Queue Depth
Connection Count
Task Wait Time
```

自动扩容。

不同服务使用不同扩容指标。

不能只看 CPU。

---

## 36. Scale Down

缩容必须：

```text
Drain
```

不能把：

```text
正在处理的 Task
Active Resource Session
```

直接杀掉。

Worker Task 需要：

```text
lease / ownership
```

或等价机制支持重新领取。

---

## 37. Event Bus

Event Bus 必须支持：

```text
multi consumer
retry
partition
consumer group
backpressure
dead letter
```

具体可以使用成熟：

```text
Kafka
NATS JetStream
RabbitMQ
Cloud Queue
```

等方案。

本项目不自研消息队列。

---

## 38. Event Partition

需要顺序的 Event 按：

```text
resourceId
taskId
subjectId
```

等局部 Key 分区。

不追求：

```text
全系统全局顺序
```

---

## 39. Cache

Cache 是性能优化，不是 Source of Truth。

适合缓存：

```text
Permission Result
Resource Metadata
Search Suggestion
Session Routing
Configuration
```

但必须支持：

```text
TTL
invalidation
fallback
```

---

## 40. Cache Failure

Cache 故障时：

```text
核心系统
```

应尽可能回退到权威存储。

不能设计成：

```text
Redis 挂了
↓
所有 Resource 永久不可用
```

除非某能力明确依赖它。

---

## 41. Cache Stampede

热点缓存失效时需要防：

```text
Cache Stampede
```

可以使用：

```text
single flight
jittered TTL
stale-while-revalidate
request coalescing
```

或等价策略。

---

## 42. Object Storage

Asset、Export Result、Import Temp、Backup 等进入：

```text
Object Storage
```

生产环境必须是：

```text
durable object storage
```

不能依赖单台应用服务器磁盘。

---

## 43. Object Storage Availability

需要监控：

```text
upload error
download error
latency
capacity
replication
```

Object Storage 故障：

```text
不能拖垮纯文本实时编辑
```

Asset 功能进入降级即可。

---

## 44. Search Engine

Search Engine 独立部署。

Search Engine 故障：

```text
Global Search unavailable
```

但：

```text
Realtime
Persistence
Permission
```

继续可用。

---

## 45. Search HA

生产 Search 至少需要：

```text
replica / shard redundancy
```

具体取决于 Search Engine。

Index 可以重建。

因此 Search 的 Disaster Recovery 优先级低于：

```text
PostgreSQL
Durable Journal
Object Storage
```

---

## 46. AI Provider

AI Provider 属于：

```text
External Degradable Dependency
```

故障时：

```text
AI Task Degraded
```

不能影响：

```text
核心 Resource Editing
```

系统可以支持多个 Provider 作为容灾选择。

---

## 47. Availability Zone

生产部署至少考虑：

```text
multiple failure domains
```

例如：

```text
multiple Availability Zones
```

关键服务不应全部部署在同一物理故障域。

---

## 48. Region

第一阶段可以单 Region 多 AZ。

不要求立即：

```text
Active-Active Multi Region
```

因为 Realtime + PostgreSQL + Consistency 的多 Region Active-Active 复杂度非常高。

优先：

```text
Single Region HA
+
Cross Region Backup / DR
```

---

## 49. 多 Region 第一阶段策略

推荐：

```text
Primary Region
= Active

DR Region
= Warm / Recoverable
```

Primary Region 发生重大灾难时：

```text
Promote DR
```

而不是一开始就设计双活写入。

---

## 50. 为什么不第一版 Multi-Region Active-Active

原因：

```text
Realtime Session Placement
PostgreSQL Write Consistency
Permission
Durable Journal
Cross Region Latency
Conflict
Cost
Operations Complexity
```

第一版做双活会显著增加系统风险。

架构保留未来扩展，但不把它作为上线前置条件。

---

## 51. Backup 总原则

Backup 必须独立于：

```text
正常业务数据库本身
```

至少需要保护：

```text
PostgreSQL
Object Storage
Critical Configuration
Encryption Metadata
```

Search Index 通常可以重建。

Cache 不需要备份。

---

## 52. PostgreSQL Backup

PostgreSQL 必须支持：

```text
Full Backup
+
WAL Archive
+
Point-in-Time Recovery
```

这样可以恢复到：

```text
某个时间点
```

而不是只能恢复昨晚整库备份。

---

## 53. Backup RPO

第一版建议生产基线：

```text
RPO ≤ 5 minutes
```

表示重大灾难情况下：

> 目标是不丢失超过 5 分钟的持久数据。

对于正常单节点故障：

```text
依靠 HA / Replication
```

目标应接近：

```text
near-zero data loss
```

---

## 54. Backup RTO

第一版建议生产基线：

```text
RTO ≤ 60 minutes
```

表示：

> 区域级灾难后，目标在 60 分钟内恢复核心系统可用。

核心系统优先级：

```text
Auth / Permission
Resource
Realtime
Persistence
```

Search / AI / Preview 可以稍后恢复。

---

## 55. RPO / RTO 分级

不同模块可以不同：

### Tier 0

```text
PostgreSQL
Permission
Resource Metadata
Persistence Journal
```

最严格。

### Tier 1

```text
Object Storage
History
Audit
```

高优先级。

### Tier 2

```text
Search
AI
Preview
Derived Index
```

可以重建或延后。

---

## 56. WAL Archive

PostgreSQL WAL 必须：

```text
持续归档
```

到独立可靠存储。

不能：

```text
Backup 和 Primary Database 在同一块磁盘
```

---

## 57. Backup Encryption

Backup 必须：

```text
encrypted at rest
encrypted in transit
```

Backup Access 需要：

```text
strict permission
audit
```

不能让普通应用账号拥有全部 Backup 删除权限。

---

## 58. Backup Retention

Backup 至少支持分层 Retention：

```text
recent
daily
weekly
monthly
```

具体保留周期由成本、业务和合规决定。

不能只保存：

```text
最近一个 Backup
```

否则发现数据损坏较晚时可能无可用恢复点。

---

## 59. Object Storage Backup

对于 Asset：

如果 Object Storage 本身提供：

```text
versioning
replication
durability
```

应启用合适能力。

同时保证：

```text
Metadata
Blob
```

可以重新关联。

---

## 60. Search Backup

Search Index 通常不作为最高优先级 Backup。

因为：

```text
Index
```

可以从 Source of Truth：

```text
Resource
Asset Metadata
Permission
```

重新构建。

重点是：

```text
Rebuild Procedure
```

可靠。

---

## 61. Audit Backup

Audit 属于敏感高价值数据。

需要：

```text
独立 Retention
Backup
Restricted Access
```

不能因为普通业务恢复只恢复 Current State 而丢失安全审计。

---

## 62. Backup Verification

Backup 成功：

```text
不等于
可以恢复
```

必须定期执行：

```text
Restore Test
```

验证：

```text
Backup 可读
WAL 可用
Schema 可恢复
Object Metadata 可关联
```

---

## 63. DR Drill

至少定期演练：

```text
PostgreSQL Restore
Region Loss
Object Storage Recovery
Search Rebuild
Queue Loss / Recovery
```

Runbook 必须经过实际演练。

---

## 64. Disaster Recovery 流程

区域级灾难恢复：

```text
Declare Incident
↓
Freeze Unsafe Writes if Needed
↓
Assess Last Durable Point
↓
Restore / Promote PostgreSQL
↓
Restore Critical Config
↓
Restore Object Storage Access
↓
Start Core Services
↓
Validate Permission / Resource / Persistence
↓
Open Realtime
↓
Resume Background Workers
↓
Rebuild Search / Derived Systems
↓
Validate
↓
Close Incident
```

---

## 65. DR 启动顺序

推荐：

```text
1 PostgreSQL
2 Critical Config / Secret
3 Permission / Auth
4 Resource Metadata
5 Persistence
6 Realtime
7 Object Storage
8 History
9 Search
10 AI
11 Import / Export
12 Analytics / Low Priority
```

避免先恢复非核心系统浪费 RTO。

---

## 66. Secret Recovery

生产 Secret 不应硬编码在镜像或仓库。

使用：

```text
Secret Manager
```

或等价能力。

DR Region 必须能够安全获得：

```text
必要 Secret
```

但不能共享 Root Key 到处复制。

---

## 67. Key Management

加密密钥需要：

```text
version
rotation
backup strategy
access audit
```

否则：

```text
数据恢复了
但密钥丢失
```

仍然不可用。

---

## 68. Rolling Deployment

服务更新默认使用：

```text
Rolling Deployment
```

新旧版本短时间共存。

因此：

```text
API
Event
Database Schema
Realtime Protocol
```

必须具备兼容窗口。

---

## 69. Backward Compatibility

发布期间：

```text
Old Version
+
New Version
```

同时运行。

不能要求：

```text
所有实例在同一秒升级
```

因此 Breaking Change 必须：

```text
Version
or
Expand / Contract
```

---

## 70. Canary Release

高风险服务建议：

```text
Canary
```

例如：

```text
Realtime
Persistence
AI Apply
Permission
```

先让少量流量进入新版本。

观察：

```text
error
latency
durable lag
disconnect
partial apply
```

再扩大。

---

## 71. Rollback

每次发布必须有：

```text
Rollback Plan
```

Rollback 不能依赖：

```text
数据库 Schema 已被不可逆破坏
```

因此数据库 Migration 必须与发布策略协调。

---

## 72. Realtime 协议升级

Realtime Protocol 必须带：

```text
protocolVersion
```

旧客户端与新服务需要存在兼容窗口。

不能一次发布后：

```text
所有旧连接立即失效
```

除非是严重安全问题。

---

## 73. Graceful Shutdown

所有服务都必须支持：

```text
SIGTERM / graceful shutdown
```

等价机制。

至少：

```text
停止接新请求
完成当前请求
释放连接
Task 安全交接
Session Drain
```

---

## 74. Worker Lease

长任务 Worker 使用：

```text
lease / heartbeat
```

或等价所有权机制。

Worker 崩溃：

```text
lease expire
↓
Task 可重新领取
```

不能永久卡在：

```text
Running
```

---

## 75. Idempotent Recovery

Task 被重新领取后：

```text
Retry
```

必须依赖：

```text
幂等设计
```

例如：

```text
Asset Process
Import Item
Search Index
Purge
```

不能重复造成不可逆副作用。

---

## 76. Network Partition

服务之间可能发生：

```text
Network Partition
```

系统不能假设：

```text
连接失败 = 对方一定没执行
```

Command 必须结合：

```text
idempotency
status query
retry
```

确认最终状态。

---

## 77. PostgreSQL Split Brain

数据库高可用必须由成熟 HA 方案保证：

```text
single writable primary
```

避免出现：

```text
两个 Primary 同时写
```

应用层不自行解决 PostgreSQL Split Brain。

---

## 78. Read-only Degraded Mode

如果 PostgreSQL 写入不可用，但部分读取仍可用：

系统可以根据安全策略进入：

```text
Read-only Degraded Mode
```

例如：

```text
允许读取已存在 Resource
禁止新建 / 修改 Permission
禁止高风险写入
```

但不能伪装写入成功。

---

## 79. Persistence Degraded Mode

如果 Durable Journal 暂时不可写：

```text
不能无限接受共享写入
```

系统应：

```text
短暂缓冲
↓
重试
↓
超过安全窗口后保护写入
```

具体行为已由 Persistence Design 定义。

Deployment 必须确保相关告警和容量支持。

---

## 80. Object Storage Degraded Mode

Object Storage 故障：

```text
文本 Resource 编辑
```

继续正常。

以下能力可能降级：

```text
Asset Upload
Asset Download
Export
Import Binary
```

---

## 81. Search Degraded Mode

Search 故障：

```text
Global Search
```

不可用。

但：

```text
Current Resource Find
```

仍可用。

---

## 82. AI Degraded Mode

AI Provider / AI Worker 故障：

```text
AI Task
```

不可用或排队。

但 Resource 系统继续运行。

---

## 83. Region Failure

Primary Region 完全不可用时：

```text
DNS / Traffic
↓
DR Region
```

恢复。

切换必须由：

```text
Incident Procedure
```

明确控制。

第一版不要求毫秒级自动区域切换。

---

## 84. DNS / Traffic Failover

区域切换后：

```text
DNS
Global Load Balancer
Traffic Manager
```

更新流量。

需要考虑：

```text
DNS TTL
existing websocket
client retry
```

客户端必须能够重新连接。

---

## 85. Client Recovery

灾难切换后：

客户端：

```text
Reconnect
↓
Authenticate
↓
Resubscribe
↓
State Vector Sync
```

本地未同步 Yjs 状态可以：

```text
重新与服务器协商 Diff
```

从而降低极短非 Durable 窗口造成的内容损失风险。

---

## 86. Offline Client Contribution

如果服务器重大故障发生前：

```text
客户端有未 Durable 的本地 Yjs Update
```

恢复后客户端重新连接时：

```text
可以通过 State Vector
```

重新补交服务器缺失 Update。

这不是 Backup 的替代品。

但可以改善实际协作恢复体验。

---

## 87. Data Corruption

如果最新 Checkpoint 损坏：

```text
Previous Verified Checkpoint
+
Durable Journal
```

恢复。

如果数据库逻辑数据损坏：

```text
PITR
```

用于恢复到损坏发生前时间点。

---

## 88. Logical Delete Accident

例如管理员错误执行：

```text
大量 Resource Trash / Delete
```

恢复优先使用：

```text
Trash / History / Audit / Application-level Restore
```

而不是立刻整库 PITR。

因为 PITR 会影响全系统其他正常数据。

---

## 89. PITR 使用边界

PITR 适用于：

```text
大范围数据库损坏
严重错误 Migration
重大误操作
Primary + Replica 数据同时损坏
```

不是普通单 Resource 恢复工具。

---

## 90. Restore Environment

执行重大数据库 Restore 时：

```text
优先恢复到隔离环境
```

进行：

```text
验证
数据比对
恢复点确认
```

再决定是否替换生产。

避免直接覆盖唯一生产实例。

---

## 91. Data Reconciliation after DR

灾难恢复后必须运行：

```text
Search Reconciliation
Asset Reference Reconciliation
Permission Cache Refresh
History Index Check
Task State Reconciliation
```

保证派生系统重新收敛。

---

## 92. In-flight Task Recovery

灾难发生前 Running 的：

```text
AI Task
Import
Export
Index
Purge
History Restore
```

恢复后：

```text
检查 lease / task state
↓
重新排队或明确失败
```

不能永久保持：

```text
Running
```

---

## 93. Export / Import Temp

灾难恢复不要求恢复所有：

```text
temporary export result
temporary import extraction
```

这些属于可重新生成数据。

恢复后可：

```text
Fail / Retry
```

降低 Backup 复杂度。

---

## 94. Search Rebuild

如果 Search Engine 数据完全丢失：

```text
Resource Metadata
+
Current Resource Content
+
Permission
```

重新构建。

因此 Search 必须有：

```text
Full Reindex Runbook
```

---

## 95. Cache Rebuild

Cache 完全丢失：

```text
系统仍应正确运行
```

只是性能下降。

Cache 逐步重新填充。

---

## 96. Capacity Headroom

生产必须预留：

```text
capacity headroom
```

不能常态运行在：

```text
CPU 95%
DB connection 99%
memory 98%
```

否则节点故障后剩余节点无法接住流量。

---

## 97. N+1 Capacity

关键服务应至少能承受：

```text
一个实例 / 一个节点故障
```

后剩余容量仍能提供核心服务。

这需要：

```text
N+1
```

或更高冗余。

---

## 98. Database Capacity

PostgreSQL 重点容量：

```text
CPU
IOPS
storage
WAL rate
connection
cache hit
vacuum
replication lag
table growth
index growth
```

必须长期趋势监控。

---

## 99. Storage Capacity

Object Storage 通常可以弹性扩展。

但仍需要监控：

```text
usage
cost
request rate
egress
orphan growth
backup replication
```

---

## 100. Load Test

上线前必须进行：

```text
API Load Test
Realtime Load Test
WebSocket Connection Test
Yjs Update Test
Hot Resource Test
PostgreSQL Load Test
Queue Backlog Test
Asset Upload Test
AI Queue Test
Import / Export Test
```

不能只压 HTTP QPS。

---

## 101. Realtime Load Test

至少测试：

```text
大量 Connection
大量 Subscription
同 Resource 多人协作
多个 Resource 并行
Reconnect Storm
Slow Consumer
Large Update
```

---

## 102. PostgreSQL Load Test

至少验证：

```text
connection pool
transaction contention
journal write
permission query
resource tree
history query
task updates
outbox
backup impact
```

---

## 103. Failure Test

上线前必须验证：

```text
kill API instance
kill Realtime worker
kill Task worker
PostgreSQL failover
Search down
Object Storage slow
Queue delay
Network error
```

确认系统真的按设计降级。

---

## 104. Chaos Scope

第一版不要求复杂 Chaos Platform。

但至少需要：

```text
可重复的 Failure Drill
```

而不是只靠架构文档假设容灾有效。

---

## 105. Environment

至少区分：

```text
Development
Staging
Production
```

生产不能与开发共享：

```text
database
object storage bucket
queue
search index
secret
```

---

## 106. Staging

Staging 应尽量与生产：

```text
架构同构
```

但规模可以更小。

用于：

```text
Migration Test
Protocol Test
DR Drill
Load Smoke Test
Release Verification
```

---

## 107. Infrastructure as Code

生产基础设施必须：

```text
Infrastructure as Code
```

或等价版本化方式管理。

避免关键部署仅存在于：

```text
人工控制台点击记录
```

具体工具由实现选择。

---

## 108. Immutable Deployment

应用部署推荐：

```text
immutable artifact
```

例如：

```text
container image
```

相同 build：

```text
Dev / Staging / Prod
```

使用不同配置部署。

避免服务器手工修改代码。

---

## 109. Image Version

所有生产服务必须能知道：

```text
buildVersion
git commit / release version
```

并进入 Observability。

---

## 110. Configuration

环境配置：

```text
database endpoint
queue endpoint
feature flag
rate limit
provider
```

与代码分离。

Secret 进入：

```text
Secret Manager
```

普通配置进入：

```text
Config System
```

---

## 111. Deployment Permission

生产发布权限必须：

```text
least privilege
audited
```

不能让所有开发人员默认拥有：

```text
生产 Root
数据库超级用户
Object Storage Admin
```

---

## 112. Database Admin

应用账号不使用：

```text
PostgreSQL superuser
```

应用使用最小权限数据库角色。

Migration、Backup、Operations 使用独立受控角色。

---

## 113. Network Segmentation

数据库、Queue、内部管理服务：

```text
不直接暴露公网
```

通过：

```text
private network
security group
firewall
service identity
```

访问。

---

## 114. TLS

外部和重要内部连接必须使用：

```text
TLS
```

包括：

```text
client → edge
service → PostgreSQL
service → object storage
service → external provider
```

具体内部 mTLS 是否第一版启用由部署环境决定。

---

## 115. Database Encryption

PostgreSQL 数据盘和 Backup：

```text
encrypted at rest
```

敏感字段如有额外需求，可使用应用层加密。

第一版不把所有普通正文做字段级加密。

---

## 116. Data Residency

第一版单 Region 部署时：

```text
Workspace
```

位于明确主 Region。

未来多 Region / 企业版可增加：

```text
data residency policy
```

架构上不把业务 ID 与具体 Region 永久绑定。

---

## 117. Region Routing

未来如果多 Region：

```text
workspaceId / resourceId
```

可映射到：

```text
home region
```

而不是把 Region 编进 resourceId。

这样支持迁移。

---

## 118. Backup Delete Protection

Backup 应具有：

```text
delete protection
retention lock
separate privilege
```

或等价能力。

避免：

```text
攻击者拿到应用账号
↓
同时删除生产和所有 Backup
```

---

## 119. Ransomware / Credential Compromise

灾难恢复必须考虑：

```text
credential compromise
```

因此：

```text
Backup Credential
Production Application Credential
```

必须分离。

---

## 120. Operations Runbook

至少需要：

```text
PostgreSQL Failover Runbook
PostgreSQL PITR Runbook
Realtime Worker Recovery Runbook
Search Rebuild Runbook
Object Storage Incident Runbook
Queue Recovery Runbook
Region Failover Runbook
Rollback Runbook
```

---

## 121. DR Ownership

Disaster Recovery 必须有明确责任边界：

```text
谁决定 Failover
谁执行 Restore
谁验证数据
谁开放流量
谁关闭 Incident
```

不能发生灾难时临时讨论流程。

---

## 122. Recovery Validation

恢复后至少验证：

```text
Login / Auth
Permission
Open Resource
Realtime Edit
Durable Persistence
History
Asset Access
Search
Task Queue
Audit
```

Search / AI 可以作为后恢复项，但必须明确当前状态。

---

## 123. Data Validation

重大恢复后应检查：

```text
PostgreSQL consistency
resource count
permission sample
journal/checkpoint recovery
asset reference
outbox backlog
task state
```

防止服务“能启动”但数据逻辑已经损坏。

---

## 124. Failback

如果临时切到 DR Region：

```text
不能立即随意切回
```

需要：

```text
Primary Region Repair
↓
Data Sync
↓
Validation
↓
Planned Failback
```

避免二次事故。

---

## 125. 第一版建议部署阶段

### Stage 1

```text
Single Region
Multi AZ
Managed PostgreSQL HA
Object Storage
Multiple API Instances
Multiple Realtime Workers
Worker Pools
Search Engine
Queue
Observability
```

这是正式生产基线。

### Stage 2

随着规模增长：

```text
Resource Sharding
Auto Scaling
Read Replica
Dedicated Worker Pools
Hot Resource Isolation
Advanced Backup
DR Region
```

### Stage 3

只有真正需要时：

```text
Multi Region Routing
Workspace Home Region
Advanced Traffic Management
Regional Data Residency
```

---

## 126. 第一版不做

第一版不要求：

```text
Multi-Region Active-Active PostgreSQL
Global Strong Consistency
自研数据库
自研消息队列
自研对象存储
所有服务 Kubernetes 化才可运行
数据库 Multi-Master
每个 Resource 独立数据库
每个 Workspace 独立集群
```

优先构建：

```text
单 Region 高可用
+
可水平扩展
+
可恢复
```

的稳定系统。

---

## 127. PostgreSQL 选型硬约束

本项目数据库统一使用：

```text
PostgreSQL
```

因此后续本地 AI 在设计：

```text
Schema
Migration
Transaction
Outbox
Permission
Task
History Metadata
Resource Metadata
```

时以 PostgreSQL 为正式生产数据库。

不应再默认：

```text
SQLite
MySQL
MongoDB
```

作为生产主数据库。

开发测试如果使用替代存储：

```text
不能改变 PostgreSQL 正式行为假设
```

---

## 128. PostgreSQL 使用原则

必须优先利用 PostgreSQL 成熟能力：

```text
transaction
foreign key
unique constraint
index
jsonb（适合时）
partitioning
advisory / row lock（适合时）
WAL
replication
PITR
```

但不能因为 PostgreSQL 功能强：

```text
把所有模块全部塞进一个巨大数据库事务
```

跨服务仍遵守 Unified Module Communication Design。

---

## 129. PostgreSQL Transaction Boundary

单个权威业务操作：

```text
Resource Metadata Change
Permission Change
Task State
Lifecycle
```

可以利用 PostgreSQL Transaction 保证本地一致性。

跨：

```text
Search
Object Storage
AI Provider
Event Consumer
```

不使用全局数据库事务。

采用：

```text
Local Transaction
+
Outbox
+
Idempotent Consumer
+
Reconciliation
```

---

## 130. PostgreSQL Lock

避免：

```text
全表锁
Workspace 级长锁
Project 级长事务
```

并发控制优先作用于：

```text
具体 Resource
具体 Member
具体 Task
具体 Operation
```

具体使用：

```text
row lock
optimistic version
advisory lock
```

由实现根据场景决定。

---

## 131. 长事务禁止

生产 PostgreSQL 应避免：

```text
长时间 Transaction
```

尤其：

```text
AI Task
Import
Export
Large Reindex
```

不能从任务开始到结束一直保持数据库 Transaction。

长流程使用：

```text
Task State
+
短事务
+
Operation Coordinator
```

---

## 132. Observability

Deployment / Scaling / DR 至少监控：

```text
instance count
instance health
deployment version
restart count
autoscaling event
drain duration
active connection
resource session distribution
hot resource
queue depth
worker saturation
PostgreSQL CPU
PostgreSQL connection
PostgreSQL replication lag
PostgreSQL WAL rate
backup success
backup age
PITR archive health
object storage health
search health
region health
RPO status
RTO drill result
```

---

## 133. 告警

至少需要：

```text
PostgreSQL Primary Down
Replication Lag High
Backup Failed
WAL Archive Stopped
Database Connection Saturated
Realtime Worker Crash Loop
Resource Session Imbalance
Reconnect Storm
Queue Backlog
Object Storage Failure
DR Backup Too Old
```

---

## 134. 核心验收场景

### 场景 1：API Instance 崩溃

多个 API 实例运行。

其中一个崩溃。

结果：

- Load Balancer 停止转发
- 其他实例继续服务
- 用户无需等待人工重启

---

### 场景 2：Realtime Worker 崩溃

Worker A 承载多个 Resource Session。

Worker A 崩溃。

结果：

```text
客户端重连
↓
Resource 重新分配
↓
Checkpoint + Journal 恢复
↓
State Vector Sync
```

Resource 不永久丢失。

---

### 场景 3：PostgreSQL Primary 故障

Primary 突然不可用。

结果：

- HA 检测
- Replica Promotion
- 应用重连
- 核心写入恢复
- 不要求重启全部服务

---

### 场景 4：Replica Lag

Read Replica 明显落后。

结果：

- Critical Permission / Lifecycle Query 不继续使用过期 Replica
- 相关指标告警
- 回退 Primary

---

### 场景 5：数据库连接耗尽风险

AI Worker 大量任务启动。

结果：

- 独立 Worker Pool 和 Connection Pool Limit 生效
- 不耗尽 PostgreSQL 全部连接
- Permission / Realtime 仍可用

---

### 场景 6：Hot Resource

一个 Resource 同时数百 / 大量协作者。

结果：

- Hotspot 被识别
- 可以独立调度 / 隔离
- 不拖慢无关 Resource

---

### 场景 7：Rolling Deployment

Realtime 发布新版本。

结果：

- Old / New Version 短时间共存
- 老连接正常 Drain
- 新连接进入新版本
- 不强制全体用户同时断线

---

### 场景 8：Worker Scale Down

系统缩容。

结果：

- Worker 先 Drain
- Running Task 安全完成或重新领取
- 不直接丢 Task

---

### 场景 9：Search Engine 全丢

Search Index 损坏。

结果：

- Resource / Realtime / Persistence 正常
- Full Reindex 重建
- 不需要从 Backup 恢复 Search 才能编辑

---

### 场景 10：Cache 全丢

Cache Cluster 被清空。

结果：

- 系统正确性不变
- 性能短暂下降
- Cache 自动回填

---

### 场景 11：Object Storage 故障

Object Storage 暂时不可用。

结果：

- 纯文本编辑继续
- Asset / Export / Import Binary 降级
- 不影响 Permission / Yjs 主链

---

### 场景 12：Region Disaster

Primary Region 完全失效。

结果：

```text
DR Runbook
↓
Restore / Promote PostgreSQL
↓
Restore Core Services
↓
Open Traffic
↓
Rebuild Derived Systems
```

目标：

```text
RPO ≤ 5 min
RTO ≤ 60 min
```

---

### 场景 13：Backup 不可恢复

定期 Restore Drill 发现某 Backup 损坏。

结果：

- 不是灾难发生时才发现
- 告警
- 修复 Backup Pipeline
- 使用其他 Recovery Point

---

### 场景 14：误删大量 Resource

管理员误操作。

结果：

- 优先使用 Trash / History / Application Restore
- 不直接进行全库 PITR
- 保留其他用户正常变化

---

### 场景 15：严重 Migration Bug

Migration 导致大量数据异常。

结果：

- 停止发布
- 使用 Rollback / PITR Runbook
- 在隔离 Restore 环境验证
- 确认恢复点后恢复

---

### 场景 16：Reconnect Storm

集群短暂重启，大量客户端同时重连。

结果：

- Client Backoff / Jitter
- Gateway Rate Protection
- Autoscaling
- 系统逐步恢复
- 不发生二次雪崩

---

### 场景 17：Running AI Task Worker Crash

AI Worker 正在任务中崩溃。

结果：

- Lease 超时
- Task 重新领取或明确 Retry
- 不永久卡 Running
- 已 Apply 的 Change 不重复执行

---

### 场景 18：Backup Credential 泄漏

应用服务凭证泄漏。

结果：

- 攻击者不能同时使用同一凭证删除所有 Backup
- Backup 使用独立权限边界

---

### 场景 19：Scale Out

流量增加。

结果：

- API / Realtime / Worker 增加实例
- Resource 重新分布
- PostgreSQL 连接保持受控
- 无全局单线程瓶颈

---

### 场景 20：数据恢复后重新收敛

PostgreSQL 从灾难恢复。

结果：

```text
Permission Cache Refresh
Search Reindex / Reconcile
Asset Reference Reconcile
Task Reconcile
History Check
```

派生系统最终恢复一致。

---

## 135. 本地 AI 实现自由度

本设计不规定：

- 必须使用 Kubernetes 还是其他容器平台
- 使用哪一家 Cloud
- 使用 Patroni 还是 Cloud Managed PostgreSQL HA
- Load Balancer 产品
- PgBouncer 配置参数
- Queue 产品
- Cache 产品
- Search Engine 产品
- Object Storage 产品
- Autoscaling 技术
- Resource Sharding 具体 Hash 算法
- Backup Retention 具体天数
- DR Region 厂商
- IaC 工具
- Secret Manager 产品

本地 AI 可以根据项目规模、预算和部署环境选择。

但必须满足本设计的高可用、扩展性、PostgreSQL、一致性、备份、故障恢复和生产运维要求。

---

## 136. 架构硬约束

1. 生产主数据库统一使用 PostgreSQL。
2. PostgreSQL 不存大型二进制文件。
3. 生产 PostgreSQL 必须具备 Primary + Replica 高可用能力。
4. PostgreSQL 必须支持 WAL Archive 和 PITR。
5. 应用服务必须使用 Connection Pool，并防止全局连接耗尽。
6. Critical Read 不能盲目使用高延迟 Replica。
7. Database Migration 必须支持新旧版本共存窗口。
8. 核心服务默认支持多实例。
9. Stateless API 不依赖本机长期状态。
10. Realtime Gateway 和 Resource Session 必须支持水平扩展。
11. Resource Session 以 resourceId 作为逻辑分片核心。
12. 不允许所有 Resource 经过全局单线程处理。
13. 同一个 Resource 的 Runtime State 必须通过安全协调路径修改。
14. Resource Ownership 切换必须具备 stale-owner fencing，新 Owner 生效后旧 Owner 不得继续权威写入。
15. Worker 崩溃后 Task 必须可以恢复 / 重试。
16. Scale Down 和 Deployment 必须 Graceful Drain。
17. Search / AI / Asset 等非核心服务故障不能拖垮核心编辑。
18. Cache 不是 Source of Truth，Cache 丢失后系统仍保持正确。
19. Object Storage 必须独立于应用服务器本地磁盘。
20. 第一阶段采用 Single Region Multi-AZ + Cross Region DR，不做 Multi-Region Active-Active。
21. 生产上线前必须明确并记录 RPO / RTO SLO；当前文档中的数值只作为容量与演练规划参考，不作为 Architecture Constitution 的固定业务承诺。
22. RPO / RTO 目标变化不得要求重写 Resource / Persistence 核心模型，应通过 HA、Backup、PITR、跨区域副本与 Runbook 能力调整。
23. 正常单节点故障依靠 HA，目标接近零数据损失。
24. Backup 必须独立、加密、可验证，并定期 Restore Drill。
25. Search Index / Cache 等派生数据应优先可重建，不作为最高级 Backup 目标。
26. Rollout 必须支持 Rolling / Canary / Rollback。
27. Protocol、Schema、Event 必须考虑 Old / New Version 共存。
28. PostgreSQL Schema 长流程不能依赖长事务。
29. 跨系统一致性继续使用 Local Transaction + Outbox + Idempotent Consumer + Reconciliation。
30. Disaster Recovery 必须有正式 Runbook 和演练。
31. Deployment / Scaling / DR 与 Observability 设计必须联动。
---

## 137. 最终模型

```text
                    Internet
                       │
                       ▼
              Edge / Load Balancer
                 │             │
                 ▼             ▼
              API Pool    Realtime Gateway Pool
                 │             │
                 │             ▼
                 │       Resource Session Pool
                 │             │
                 └──────┬──────┘
                        │
                        ▼
                   Service Layer
                        │
        ┌───────────────┼────────────────┐
        ▼               ▼                ▼
   PostgreSQL        Event / Queue   Object Storage
 Primary + Replica                    │
        │                             │
        │                             └── Assets / Export / Backup
        │
        ├── Metadata
        ├── Permission
        ├── Task
        ├── History
        ├── Outbox
        └── Durable State Metadata

Derived Systems:
Search / Cache / AI / Preview
```

高可用：

```text
Instance Failure
→ Horizontal Redundancy

Realtime Worker Failure
→ Session Rebuild

PostgreSQL Primary Failure
→ Replica Promotion

Region Failure
→ DR Region Restore / Promote
```

数据恢复：

```text
PostgreSQL Full Backup
+
WAL Archive
↓
PITR

Object Storage
+
Replication / Versioning
↓
Asset Recovery

Source of Truth
↓
Rebuild Search / Cache / Derived Data
```

本项目生产部署的主线是：

> PostgreSQL 保住权威业务状态，Durable Journal 保住实时内容，Object Storage 保住大文件，Resource Sharding 保证实时协作可横向扩展，Derived Systems 可以重建，Backup + PITR + DR Runbook 保证真正发生灾难时系统仍然能恢复。
