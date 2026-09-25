# Repository & Module Layout Design

> Status: Normative
>
> Canonical Owner: repository layout, module boundaries and dependency direction

## 1. 目标

本设计正式锁定代码仓库目录和模块边界，让本地 AI 能明确回答：

```text
代码应该放哪里
模块允许依赖谁
Contract 放哪里
Domain Logic 放哪里
HTTP / WebSocket / Worker Adapter 放哪里
Migration 放哪里
跨语言共享什么
```

---

## 2. Monorepo

正式采用：

```text
Monorepo
```

第一阶段所有：

```text
Web
API
Realtime
Workers
Contracts
Migrations
Infrastructure
Tests
Architecture Docs
```

位于同一个 Repository。

---

## 3. Root Layout

```text
repo/
├── AGENTS.md
├── README.md
├── justfile
├── package.json
├── pnpm-workspace.yaml
├── pnpm-lock.yaml
├── pyproject.toml
├── uv.lock
│
├── apps/
│   └── web/
│
├── services/
│   ├── api/
│   └── realtime/
│
├── workers/
│   ├── ai/
│   ├── import_export/
│   ├── asset/
│   ├── search/
│   └── maintenance/
│
├── packages/
│   ├── ts/
│   └── py/
│
├── contracts/
├── migrations/
├── tests/
├── infra/
├── scripts/
└── docs/
    ├── architecture/
    ├── adr/
    ├── product/
    │   └── features/
    ├── behavior/
    │   ├── features/
    │   └── example-maps/
    ├── superpowers/
    │   └── plans/
    └── runbooks/
```

`docs/` 子目录职责：

```text
architecture/ → 00-29 架构设计文档集，Normative，不得改写
adr/          → 架构决策记录，NNNN-short-name.md
product/      → 产品线文档
  features/     → 每个产品模块一份 PRD
behavior/     → 行为规格线文档
  features/     → 每个产品模块一份行为规格
  example-maps/ → 行为示例映射
superpowers/  → 工程方法论流程产物
  plans/        → 实施计划（writing-plans 输出）
runbooks/     → 运维 Runbook
```

`product/` `behavior/` `superpowers/` 属于文档工作流扩展，不与 `apps/ services/ workers/ packages/ contracts/ migrations/ tests/ infra/ scripts/` 的模块边界或依赖方向相关，因此不触发 §72 第 20 条的 ADR 要求。

---

# Part A: Architecture / AI Loading

## 4. docs/architecture

当前 `00-29` 正式进入：

```text
docs/architecture/
```

---

## 5. AGENTS.md

Root `AGENTS.md` 只保存：

```text
开发原则
Constitution 加载规则
模块边界
质量门槛
禁止事项
```

禁止复制整套架构文档。

---

## 6. Local AI Loading Rule

本地 AI 每次实现任务：

```text
1. 读 00-ARCHITECTURE-CONSTITUTION.md
2. 定位 Canonical Owner
3. 只加载 Owner + Direct Dependencies
4. 定位目标 Module README
5. 再修改代码
```

默认禁止把所有架构文档一次性塞进 Context。

---

## 7. ADR

技术或硬边界变更：

```text
docs/adr/NNNN-short-name.md
```

ADR 记录：

```text
Context
Decision
Alternatives
Consequences
Migration
Rollback
```

---

# Part B: Web

## 8. apps/web

```text
apps/web/
├── src/
│   ├── app/
│   ├── routes/
│   ├── features/
│   ├── runtime/
│   ├── components/
│   ├── styles/
│   ├── telemetry/
│   └── main.tsx
├── public/
├── index.html
├── vite.config.ts
└── package.json
```

---

## 9. app/

只负责：

```text
bootstrap
providers
router assembly
global error boundary
SDK initialization
```

---

## 10. routes/

只负责：

```text
URL mapping
route-level loading boundary
feature composition
```

Route 不能保存业务状态真相。

---

## 11. features/

正式按功能域：

```text
features/
├── auth/
├── workspace/
├── project/
├── resource-tree/
├── resource/
├── document-editor/
├── text-editor/
├── comment/
├── notification/
├── search/
├── history/
├── ai/
├── asset/
├── import-export/
├── permission/
├── task-center/
├── offline/
├── account/
└── trash/
```

---

## 12. Feature Layout

推荐统一：

```text
feature/
├── components/
├── hooks/
├── model/
├── queries/
├── commands/
└── index.ts
```

含义：

```text
components → UI adapter
hooks      → React integration
model      → local feature state / selectors
queries    → Client SDK query composition
commands   → Client SDK command composition
```

---

## 13. UI 边界

UI / UX 由用户设计。

架构只规定：

```text
component 不直接 fetch
component 不直接 new WebSocket
component 不直接写 IndexedDB
component 不知道 PostgreSQL / NATS / OpenSearch
```

---

# Part C: Frontend Runtime

## 14. runtime/

```text
apps/web/src/runtime/
├── session/
├── network/
├── resource/
├── navigation/
├── permission/
└── telemetry/
```

---

## 15. Resource Runtime

`runtime/resource` 组合：

```text
Resource Metadata
Capability
Local Y.Doc / Y.Text
Editor Adapter
WebSocket Subscription
Offline Store
Awareness
Sync / Durable State
Resource Lifecycle
```

它不是普通 Zustand Global Store。

---

## 16. WebSocket Ownership

任何 Feature：

```text
不得自行创建 WebSocket
```

正式入口只有：

```text
packages/ts/realtime-client
```

它负责：

```text
connection pool
multiplex
subscription
reconnect
watermark
frame codec
```

---

# Part D: TypeScript Packages

## 17. packages/ts

```text
packages/ts/
├── contracts/
├── client-sdk/
├── realtime-client/
├── realtime-protocol/
├── editor-core/
├── resource-runtime/
├── resource-adapters/
└── shared/
```

---

## 18. contracts

```text
Generated Only
```

来自 `/contracts`。

禁止手改 generated DTO。

---

## 19. client-sdk

负责：

```text
HTTP Command
HTTP Query
Error Envelope
requestId
idempotencyKey
Abort / Retry Policy
```

Feature 只调用 `client-sdk`。

---

## 20. realtime-client

负责：

```text
native WebSocket
WSS auth
Control Frame
Yjs Binary Frame
Awareness
Resource Event
Account Event
Task Stream
Sync / Durable Watermark
Reconnect
Backpressure
```

不包含 UI。

---

## 21. editor-core

负责：

```text
Tiptap / ProseMirror Schema
NodeIdentityExtension
Document Command
Editor Transaction
Yjs Binding
Undo origin policy
```

---

## 22. resource-runtime

负责：

```text
Resource Runtime state machine
Offline lifecycle
Sync state
Permission reaction
Dispose
```

---

## 23. resource-adapters

```text
resource-adapters/
├── document/
├── code/
├── markdown/
└── text/
```

每种 Resource Type 提供：

```text
editor adapter
preview adapter
navigation adapter
local find adapter
```

---

## 24. shared

只允许真正通用且无 Domain 所属的：

```text
small utility
time helper
assertion
base technical helper
```

禁止形成 `shared/business.ts` 垃圾场。

---

# Part E: Python Core

## 25. packages/py

```text
packages/py/
├── core/
├── infrastructure/
├── task-runtime/
└── contracts/
```

---

## 26. core

```text
packages/py/core/src/app_core/
├── account/
├── session/
├── workspace/
├── project/
├── resource/
├── permission/
├── history/
├── asset/
├── search/
├── ai/
├── import_export/
├── comment/
├── notification/
└── operations/
```

`account/` 与 `session/` 是两个独立 Core Domain Module：前者拥有 Account 生命周期（注册、邮箱验证、密码找回、账号删除与宽限期），后者拥有 Session 生命周期（登录、登出、重新认证、设备配额与替换、会话失效）。两者的语义边界、状态机与安全规则统一由 `16-Account-Auth-Session-Design.md` 管辖，模块拆分不改变 Canonical Owner。

---

## 27. Domain Module Layout

每个模块：

```text
module/
├── domain/
├── application/
├── ports/
└── README.md
```

---

## 28. domain

只放：

```text
Entity
Value Object
Invariant
Policy
Domain Event semantic definition
```

禁止 Import：

```text
FastAPI
SQLAlchemy
NATS
Valkey
OpenSearch
S3 SDK
```

---

## 29. application

负责：

```text
Command Handler
Query Handler
Use Case
Transaction orchestration
Cross-domain application coordination
```

---

## 30. ports

定义：

```text
Repository Port
Event Publisher Port
Object Storage Port
Search Port
Provider Port
Permission Port
```

---

# Part F: Infrastructure

## 31. packages/py/infrastructure

```text
packages/py/infrastructure/src/app_infra/
├── postgres/
├── nats/
├── valkey/
├── opensearch/
├── s3/
├── email/
├── oauth/
└── telemetry/
```

它实现 `core.ports`。

---

## 32. PostgreSQL Repository

按 Domain Owner：

```text
postgres/
├── account/
├── session/
├── resource/
├── permission/
├── history/
├── comment/
├── task/
└── ...
```

其他模块禁止直接修改非 Owner 表。

---

# Part G: Generic Task Runtime

## 33. packages/py/task-runtime

负责 `25`：

```text
Task Claim
Attempt
Lease
Heartbeat
Fencing
Retry
Cancel
Progress
Reconciliation
Worker Host
```

Domain Handler 通过 Registry 注入。

---

# Part H: API Service

## 34. services/api

```text
services/api/
├── src/api/
│   ├── main.py
│   ├── routes/
│   ├── dependencies/
│   ├── middleware/
│   ├── errors/
│   └── bootstrap/
├── tests/
└── pyproject.toml
```

---

## 35. Route Layout

```text
routes/
├── auth.py
├── workspace.py
├── project.py
├── resource.py
├── comment.py
├── notification.py
├── search.py
├── history.py
├── ai.py
├── asset.py
├── import_export.py
├── permission.py
└── task.py
```

---

## 36. API 只做 Interface Adapter

禁止：

```text
@router.post(...)
async def route(...):
    await session.execute(业务 SQL)
```

正式：

```text
HTTP
↓
Generated Request DTO
↓
Application Command / Query
↓
Generated Response DTO
```

---

# Part I: Realtime Service

## 37. services/realtime

```text
services/realtime/
├── src/
│   ├── server/
│   ├── protocol/
│   ├── connection/
│   ├── subscription/
│   ├── resource/
│   ├── auth/
│   ├── permission/
│   ├── persistence/
│   ├── nats/
│   ├── telemetry/
│   └── main.ts
├── tests/
└── package.json
```

---

## 38. server

只负责：

```text
HTTP Upgrade → WebSocket
connection lifecycle
socket limits
```

---

## 39. protocol

负责：

```text
frame codec
protocol version
Control / Sync / Awareness / System
watermark
```

---

## 40. connection

负责：

```text
WebSocket connection
heartbeat
backpressure
outbound queue
connection auth context
```

---

## 41. subscription

负责：

```text
resource subscription
account subscription
task subscription
multiplex routing
```

---

## 42. resource

负责：

```text
ResourceSession
Y.Doc runtime
ownership epoch
fencing
idle / eviction
```

---

## 43. permission

Realtime 不自行定义 Role。

只消费正式：

```text
Capability Contract
PermissionChanged Event
```

---

## 44. persistence

只负责：

```text
Yjs Journal
Checkpoint metadata
Durable Watermark
```

不负责 User-visible History Product Logic。

---

# Part J: Workers

## 45. workers

```text
workers/
├── ai/
├── import_export/
├── asset/
├── search/
└── maintenance/
```

---

## 46. Worker 定位

Worker 是：

```text
Task Runtime Host
+
Domain Application Handler
```

不是新的 Domain Owner。

---

## 47. AI Worker

处理：

```text
model call
tool orchestration
context building
ChangeSet generation
```

正式 Apply 仍回到 Domain Application。

---

## 48. Import / Export Worker

处理：

```text
parse
validate
convert
package
```

不直接写 Resource 内部表绕过 Lifecycle。

---

## 49. Asset Worker

处理：

```text
scan
metadata
preview
transcode
derived asset
```

---

## 50. Search Worker

处理：

```text
incremental index
reindex
reconciliation
```

---

## 51. Maintenance Worker

处理：

```text
checkpoint
compaction
purge
reconciliation
backfill
repair
```

---

# Part K: Contracts

## 52. contracts/

```text
contracts/
├── registry.yaml
├── ids/
├── errors/
├── commands/
├── queries/
├── events/
├── tasks/
├── streams/
├── realtime/
└── openapi/
```

详细规则见 `28`。

---

## 53. Generated Output

语言生成物：

```text
packages/ts/contracts
packages/py/contracts
```

禁止把生成代码当 Canonical Source。

---

# Part L: Migrations

## 54. PostgreSQL

```text
migrations/postgres/
├── env.py
├── versions/
└── README.md
```

只由 Alembic 管理。

---

## 55. Resource Schema Migration

Yjs / Document Schema Migration 不放 Alembic。

进入：

```text
packages/py/core/resource/migrations/
```

执行器可以由 Maintenance Worker 调用。

---

# Part M: Tests

## 56. Root tests

```text
tests/
├── contract/
├── integration/
├── e2e/
├── realtime/
├── offline/
├── migration/
├── security/
├── load/
└── fixtures/
```

---

## 57. Unit Tests

Unit Test 与模块共址。

Root Tests 只负责：

```text
cross-module
cross-process
system-level
```

---

## 58. Fixtures

保存：

```text
old Yjs checkpoint
old document schema
malformed archive
webhook fixture
provider response fixture
```

禁止真实用户数据。

---

# Part N: Infra

## 59. infra

```text
infra/
├── compose/
├── docker/
├── helm/
├── terraform/
├── envoy/
├── otel/
├── nats/
├── opensearch/
└── grafana/
```

---

## 60. compose

只负责 Local Infrastructure。

---

## 61. helm

负责 Kubernetes Application Release。

---

## 62. terraform

负责：

```text
network
cluster
managed PostgreSQL
object storage
OpenSearch
DNS
load balancer
secret backend
```

不负责业务 Migration。

---

# Part O: Dependency Direction

## 63. Python

```text
services/api
      ↓
core.application
      ↓
core.domain

infrastructure
      ↑ implements
core.ports

workers
      ↓
task-runtime
      ↓
core.application
```

---

## 64. Frontend

```text
apps/web
  ↓
client-sdk
resource-runtime
editor-core
realtime-client
  ↓
contracts
```

---

## 65. Realtime

```text
services/realtime
  ↓
packages/ts/contracts
packages/ts/realtime-protocol
Yjs
y-protocols
pg
NATS client
```

Realtime 禁止 Import `apps/web`。

---

## 66. Contract Bottom Layer

`contracts` 不依赖任何 Application Module。

---

# Part P: Domain Ownership

## 67. Table Owner

每张 PostgreSQL Table 必须有唯一：

```text
Domain Owner
```

其他模块：

```text
可以读正式 Read Model
不得随意更新 Owner Table
```

---

## 68. Cross-domain Transaction

Modular Monolith 允许同一个 PostgreSQL Transaction 跨 Domain Table。

但必须由：

```text
Application Use Case
```

显式编排。

不是因为共享数据库就可以任意互写。

---

# Part Q: Module README

## 69. 每个核心模块必须有 README

至少说明：

```text
Responsibility
Canonical Docs
Public Interfaces
Allowed Dependencies
Owned Tables
Produced Events
Consumed Events
Tests
```

---

# Part R: Local AI Rules

## 70. AI 修改前

必须：

```text
定位目标 Module
读取 README
读取 Constitution
读取 Canonical Owner
检查依赖方向
```

---

## 71. 禁止

本地 AI 不得为了“方便”自动：

```text
把业务函数塞 shared
跨层 import
Route 里写 Domain SQL
Worker 复制业务规则
Feature 直接 fetch
Feature 自建 WebSocket
Generated Contract 手改
```

---

# Part S: Hard Constraints

## 72. 架构硬约束

1. Repository 使用 Monorepo。
2. Web 位于 `apps/web`。
3. API 位于 `services/api`。
4. Realtime WebSocket Service 位于 `services/realtime`。
5. Worker 位于 `workers/*`。
6. Python Domain/Application Core 位于 `packages/py/core`。
7. Infrastructure Adapter 位于 `packages/py/infrastructure`。
8. Generic Task Runtime 位于 `packages/py/task-runtime`。
9. TS Client Runtime 位于 `packages/ts/*`。
10. Contract Source 位于 `/contracts`。
11. PostgreSQL Migration 位于 `/migrations/postgres`。
12. Domain 不直接依赖 Framework / Infrastructure。
13. API Route 不包含核心业务逻辑。
14. Worker 不复制 Domain Logic。
15. Frontend Feature 不直接 raw fetch / raw WebSocket。
16. 所有 WebSocket 创建和协议处理归 `realtime-client` / `services/realtime`。
17. Generated Contract Code 不手改。
18. 每张 PostgreSQL Table 有唯一 Domain Owner。
19. `shared` 不得成为业务垃圾场。
20. 顶层目录或依赖方向改变需要 ADR。
