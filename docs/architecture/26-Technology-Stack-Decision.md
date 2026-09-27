# Technology Stack Decision

> Status: Normative
>
> Canonical Owner: production runtime, framework and infrastructure technology choices
>
> Baseline date: 2026-09-22

## 1. 目标

`01-25` 先固定业务边界、状态所有权、一致性与安全语义。本文件开始正式冻结工程技术栈，避免本地 AI 在实现阶段自行选择另一套框架、Queue、Search 或 Realtime Server。

本文件锁定“技术产品与大版本基线”；具体 patch 版本由 `pnpm-lock.yaml`、`uv.lock`、Container Digest 锁定。

---

## 2. 第一阶段物理架构

正式采用：

```text
React Web Client
   │
   ├── HTTPS: Command / Query
   ▼
FastAPI Modular Monolith
   │
   ├── PostgreSQL
   ├── NATS JetStream
   ├── Valkey
   ├── OpenSearch
   └── S3-compatible Object Storage

React Web Client
   │
   └── WSS: Realtime Stream
        ▼
TypeScript Realtime Service
        │
        ├── Yjs / y-protocols
        ├── PostgreSQL collab schema
        └── NATS JetStream

NATS JetStream
   │
   └── Worker Pools
        ├── AI
        ├── Import / Export
        ├── Asset
        ├── Search
        └── Maintenance
```

第一阶段不是 Domain 微服务群，而是：

```text
Modular Monolith API
+
Dedicated Realtime Service
+
Dedicated Worker Pools
```

---

# Part A: WebSocket 是正式实时协议

## 3. Transport 分工

正式固定：

```text
HTTP/HTTPS
→ Command / Query / Upload Control Plane

WebSocket/WSS
→ Realtime collaboration / Resource Event / Account Event / Task Stream

S3 HTTPS
→ Large binary data plane
```

核心实时协作必须使用：

```text
WebSocket
```

不是 SSE。

---

## 4. WebSocket 连接模型

默认：

```text
一个 Client Session
→ 一个长连接 WebSocket
→ multiplex 多个 Resource / Account / Task Subscription
```

高流量 Resource 可以由 Realtime Client / Gateway：

```text
隔离到额外 WebSocket connection
```

这属于负载隔离，不改变协议语义。

---

## 5. WebSocket Frame

WebSocket 上承载：

```text
Control
Yjs Sync
Yjs Update
Awareness
System
Resource Event
Account Event
Task Progress
Sync / Durable Watermark
```

Yjs Update 保持：

```text
binary
```

不 Base64 包进普通 JSON。

---

## 6. 不使用 Socket.IO

第一版不用：

```text
Socket.IO
```

原因：

```text
Yjs 本身使用 binary protocol
我们已有正式 Control / Sync / Awareness / System frame 语义
避免叠加第二套事件协议与 fallback 语义
```

---

# Part B: Frontend

## 7. Runtime

正式锁定：

```text
Node.js 24 LTS
TypeScript 5.x
React 19
Vite 8
pnpm
```

Node.js 使用 LTS，不使用 Current 版本作为生产基线。

---

## 8. Web Framework

主前端：

```text
React 19 + Vite 8 SPA
```

不使用 Next.js 作为核心框架。

原因：产品核心是：

```text
long-lived Workspace
Local Y.Doc
WebSocket
Offline Runtime
high-interaction editor
```

SSR 不是架构主需求。

---

## 9. Router

使用：

```text
React Router 7
```

负责：

```text
Workspace / Project / Resource / Share / Account / History Preview
```

---

## 10. Server State

使用：

```text
TanStack Query 5
```

管理：

```text
Workspace
Project Tree
Resource Metadata
Permission
Comment
Notification
History Metadata
Task
Search Result
```

禁止把以下对象放入 Query Cache：

```text
Y.Doc
EditorView
Awareness
WebSocket
```

---

## 11. Local UI State

使用：

```text
Zustand 5
```

只管理：

```text
UI state
application-local state
cross-feature presentation state
```

不能复制 Server State。

---

## 12. Rich Document Editor

使用：

```text
Tiptap
ProseMirror
Yjs
y-prosemirror
```

正式路径：

```text
Tiptap
↓
ProseMirror Transaction
↓
y-prosemirror
↓
Y.Doc
↓
WebSocket
```

---

## 13. Code / Markdown / Text Editor

使用：

```text
CodeMirror 6
```

正文 Source of Truth：

```text
Y.Text
```

---

## 14. Offline

使用：

```text
IndexedDB
y-indexeddb
Dexie
```

职责：

```text
y-indexeddb → Y.Doc offline persistence
Dexie       → metadata / recovery / local runtime state
```

禁止用 `localStorage` 保存完整 Resource 正文。

---

## 15. UI 工程基础

用户负责全部 UI / UX。

工程只锁：

```text
Tailwind CSS 4
CSS Variables
Radix UI Primitives
```

Radix 仅作为无视觉强绑定的 accessibility / behavior primitive，不作为产品视觉 Design System。

---

# Part C: Client Contract

## 16. Contract Format

普通业务 Contract：

```text
JSON Schema 2020-12
OpenAPI 3.1
```

详细规则由 `28-Contract-Schema-Registry-Design.md` 定义。

---

## 17. TypeScript HTTP SDK

使用：

```text
openapi-typescript
openapi-fetch
```

Feature Module 不直接散落 `fetch()`。

---

## 18. Runtime Validation

TypeScript 使用：

```text
Ajv
```

验证：

```text
Event
Realtime Control Payload
Offline Persisted Metadata
External Provider Payload after adapter boundary
```

---

# Part D: Backend API

## 19. Python Runtime

正式锁定：

```text
Python 3.12
uv
```

选择 3.12 是为了当前 AI / data / parser 依赖生态的兼容和稳定，不追逐最新 Python Major。

---

## 20. Framework

使用：

```text
FastAPI
Pydantic v2
Uvicorn
```

Route 只做：

```text
HTTP Adapter
Auth Context
Schema Validation
Application Command / Query 调用
Response Mapping
```

Domain Logic 不写在 Route。

---

## 21. External HTTP

Python 外部 HTTP 统一：

```text
httpx
```

不得各模块混用 `requests / aiohttp / urllib`。

---

# Part E: PostgreSQL

## 22. Database

正式锁定：

```text
PostgreSQL 18
```

生产始终跟随 18.x 当前安全 patch。

不在 PostgreSQL 19 Beta 阶段迁移生产基线。

---

## 23. Python Data Access

使用：

```text
SQLAlchemy 2.x
psycopg 3
```

默认使用 Async SQLAlchemy API。

---

## 24. Realtime Data Access

Realtime TypeScript Service 对 `collab` 专属表使用：

```text
node-postgres (pg)
```

只允许访问 Realtime / Persistence 所属表。

Realtime Service 不直接修改：

```text
auth
permission
comment
business lifecycle
```

这些仍走正式模块接口 / Event。

---

## 25. Migration

生产数据库唯一 Migration 工具：

```text
Alembic
```

禁止：

```text
auto-create production schema
auto-sync schema
ORM startup alter table
```

---

## 26. Connection Pool

生产：

```text
PgBouncer
```

API、Realtime、Worker 分别有连接预算。

---

# Part F: Business IDs

## 27. ID

跨模块业务实体统一优先：

```text
UUIDv7
```

例如：

```text
userId
workspaceId
projectId
resourceId
taskId
commentId
assetId
eventId
```

不得使用数据库自增 ID 作为跨模块公开身份。

---

# Part G: Realtime Service

## 28. Runtime

正式锁定：

```text
Node.js 24 LTS
TypeScript 5.x
Yjs
y-protocols
lib0
ws
pg
```

---

## 29. 为什么 Realtime 使用 TypeScript

原因：

```text
Yjs 官方/主生态在 JavaScript / TypeScript
Y.Doc / y-protocols / Awareness 可以直接使用原生实现
无需在 Python 重写 CRDT 协议
```

---

## 30. Realtime Server 不使用 Hocuspocus 作为 Canonical Runtime

不把：

```text
Hocuspocus
y-websocket server
```

作为最终系统核心 Server Framework。

因为当前系统需要：

```text
Resource multiplexing
Permission live invalidation
Sync / Durable Watermark
Ownership Epoch / Fencing
Custom Journal
Backpressure / Fair Scheduling
```

因此直接基于：

```text
ws + Yjs + y-protocols + lib0
```

实现 `05` 的正式协议。

---

# Part H: Queue / Event Bus

## 31. Messaging

正式锁定：

```text
NATS
JetStream
```

---

## 32. 分工

```text
Core NATS
→ low-latency internal notification / coordination where safe

JetStream
→ Durable Event
→ Async Task execution trigger
→ Retryable delivery
```

Task Source of Truth 仍是：

```text
PostgreSQL
```

---

## 33. 不使用 Celery 作为 Task 架构

原因：

```text
Worker 未来可能是 Python / TypeScript / Rust
25 已定义 PostgreSQL Task State + Attempt + Lease + Fencing
不能让 Python-only Framework 变成 Task Source of Truth
```

---

## 34. 不使用 Kafka / RabbitMQ 双栈

第一阶段不额外维护：

```text
Kafka
RabbitMQ
Redis Queue
```

需要变更必须 ADR。

---

# Part I: Cache

## 35. Cache

正式锁定：

```text
Valkey 9
```

使用当前 9.x 安全 patch。

---

## 36. 用途

```text
hot metadata cache
permission cache
session invalidation acceleration
rate limit counter
ephemeral coordination
```

禁止作为：

```text
Session truth
Permission truth
Task truth
Resource truth
Durable Journal
```

---

# Part J: Search

## 37. Search Engine

正式锁定：

```text
OpenSearch 3.x
```

当前生产 baseline：

```text
3.8+ compatible release
```

---

## 38. Search Scope

承担：

```text
keyword full-text
CJK search
filter
ranking
snippet
future vector k-NN / hybrid search
```

第一阶段不再引入另一套专用 Vector DB。

---

# Part K: Object Storage

## 39. Storage API

正式统一：

```text
S3-compatible API
```

---

## 40. Local / CI

使用：

```text
MinIO
```

---

## 41. Production

Stage 0 单 CVM 例外使用本机 MinIO；多实例生产继续使用以下托管 S3 兼容存储（ADR 0054）。

单 CVM Stage 0 使用本机 MinIO，例外范围见 ADR 0054。

使用：

```text
Managed S3-compatible Object Storage
```

具体云厂商可替换，但业务代码只依赖统一 `ObjectStoragePort`。

---

## 42. Upload

大型上传正式使用：

```text
Signed URL
+
S3 Multipart Upload
```

支持失败重试和续传。

---

# Part L: Observability

## 43. Standard

正式锁定：

```text
OpenTelemetry
```

---

## 44. Stack

```text
OpenTelemetry Collector
Prometheus
Grafana
Loki
Tempo
```

分工：

```text
Metrics → Prometheus
Logs    → Loki
Traces  → Tempo
UI      → Grafana
```

Audit 不存 Loki 作为唯一真相。

---

# Part M: Testing

## 45. Frontend

```text
Vitest
React Testing Library
```

---

## 46. Browser / Realtime E2E

```text
Playwright
```

必须覆盖：

```text
真实 WebSocket
multi-tab
offline / reconnect
```

---

## 47. Python

```text
pytest
pytest-asyncio
```

---

## 48. Infrastructure Integration

使用：

```text
Testcontainers
```

启动真实：

```text
PostgreSQL
NATS
Valkey
OpenSearch
MinIO
```

---

## 49. Load

使用：

```text
k6
```

HTTP 与 WebSocket 都必须压测。

---

## 50. Security CI

使用：

```text
Gitleaks
Trivy
Semgrep
```

---

# Part N: Build / Package

## 51. JavaScript

统一：

```text
pnpm
```

只提交：

```text
pnpm-lock.yaml
```

禁止并存 npm/yarn/bun lockfile。

---

## 52. Python

统一：

```text
uv
uv.lock
```

---

## 53. Root Task Runner

使用：

```text
just
```

统一入口：

```text
just dev
just lint
just test
just contract
just migrate
just e2e
just load-test
```

---

# Part O: Local Development

## 54. Local Infrastructure

使用：

```text
Docker Compose
```

运行：

```text
PostgreSQL
NATS JetStream
Valkey
OpenSearch
MinIO
OTel Collector
Prometheus
Grafana
Loki
Tempo
```

Application Process 可以 Host 运行以获得快速 Reload。

---

# Part P: Production

## 55. Container

所有 Service：

```text
OCI / Docker Image
BuildKit
multi-stage build
non-root runtime
```

---

## 56. Orchestrator

正式多实例高可用生产：

```text
Kubernetes
```

单 CVM Stage 0部署仅在 ADR 0054 范围内允许使用 Docker Compose；该配置不满足应用层多实例高可用基线。

---

## 57. Deployment Package

正式多实例高可用生产使用：

```text
Helm
```

ADR 0054 的单 CVM Stage 0使用独立的 `compose.server.yaml`。

---

## 58. Infrastructure as Code

使用：

```text
Terraform
```

---

## 59. Edge

Kubernetes Edge：

```text
Gateway API
Envoy Gateway
```

支持：

```text
HTTPS
WSS WebSocket Upgrade
long-lived WebSocket timeout
routing
rate limit integration
```

必须显式保证 WebSocket 长连接不会被默认短 HTTP Timeout 切断。

---

## 60. Secrets

使用：

```text
External Secrets Operator
```

连接云厂商：

```text
Secret Manager / Key Vault
```

Secret 不进入 Git / Helm 明文 values。

---

# Part Q: CI/CD

## 61. CI

使用：

```text
GitHub Actions
```

---

## 62. Registry

默认：

```text
GitHub Container Registry (GHCR)
```

如果部署环境已有内部 OCI Registry，可通过 ADR 替换。

---

# Part R: Serialization

## 63. 普通业务数据

```text
JSON / UTF-8
JSON Schema 2020-12
OpenAPI 3.1
```

---

## 64. Event

NATS / JetStream Event：

```text
JSON
+
eventId
+
schemaVersion
+
trace context
```

第一阶段不再引入 Protobuf / Avro Schema Registry。

---

## 65. Realtime

WebSocket：

```text
Control / System metadata
→ compact typed frame

Yjs payload
→ binary
```

具体 frame layout 由 `05` + `28` 定义。

---

# Part S: Final Stack

## 66. 总表

| Layer | Technology |
| --- | --- |
| Frontend Runtime | Node.js 24 LTS |
| Language | TypeScript 5.x |
| Web | React 19 |
| Build | Vite 8 |
| Routing | React Router 7 |
| Server State | TanStack Query 5 |
| Local UI State | Zustand 5 |
| Rich Editor | Tiptap + ProseMirror |
| CRDT | Yjs + y-prosemirror |
| Code/Text Editor | CodeMirror 6 |
| Offline | IndexedDB + y-indexeddb + Dexie |
| Styling primitives | Tailwind CSS 4 + Radix UI Primitives |
| API Runtime | Python 3.12 |
| API Framework | FastAPI + Pydantic v2 + Uvicorn |
| Python Package | uv |
| Python DB | SQLAlchemy 2 + psycopg 3 |
| Realtime DB | node-postgres (`pg`) limited to collab schema |
| Migration | Alembic |
| Database | PostgreSQL 18 |
| DB Proxy | PgBouncer |
| Realtime Runtime | Node.js 24 + TypeScript |
| Realtime Transport | **WebSocket / WSS** |
| WS Server | `ws` |
| Realtime Protocol | Yjs + y-protocols + lib0 |
| Queue / Event Bus | NATS + JetStream |
| Cache | Valkey 9 |
| Search | OpenSearch 3.x |
| Object Storage | S3-compatible |
| Local Object Storage | MinIO |
| Contract | JSON Schema 2020-12 + OpenAPI 3.1 |
| HTTP SDK | openapi-typescript + openapi-fetch |
| Runtime JSON Validation | Ajv |
| Observability | OpenTelemetry |
| Metrics | Prometheus |
| Dashboard | Grafana |
| Logs | Loki |
| Traces | Tempo |
| Frontend Test | Vitest + React Testing Library |
| Browser E2E | Playwright |
| Backend Test | pytest + pytest-asyncio |
| Integration | Testcontainers |
| Load | k6 |
| Security CI | Gitleaks + Trivy + Semgrep |
| JS Package Manager | pnpm |
| Root Task Runner | just |
| Local Infra | Docker Compose |
| Production HA | Kubernetes + Helm + Terraform |
| Single-CVM Stage 0 (ADR 0054) | Docker Compose + existing OneTree Nginx/Certbot |
| Edge | Gateway API + Envoy Gateway |
| Secrets | External Secrets Operator |
| CI/CD | GitHub Actions |

---

# Part T: Hard Constraints

## 67. 架构硬约束

1. 核心实时协作正式使用 WebSocket/WSS，不使用 SSE 代替双向协作协议。
2. HTTP 负责 Command / Query；WebSocket 负责 Realtime Stream；S3 负责大型 Binary Data Plane。
3. 第一阶段采用 Modular Monolith API + Dedicated Realtime + Worker Pools，不拆 Domain 微服务群。
4. Web 使用 React + Vite；Realtime 使用 TypeScript + Yjs + `ws`。
5. PostgreSQL 18 是唯一权威业务数据库。
6. Python 主业务数据访问使用 SQLAlchemy 2 + psycopg 3；Realtime 仅对 collab schema 使用 `pg`。
7. Alembic 是生产 PostgreSQL Schema Migration 唯一入口。
8. NATS JetStream 是 Durable Event / Task Trigger 基础设施。
9. Valkey 只做 Cache / Ephemeral Acceleration。
10. OpenSearch 是全文和未来 Vector Search 基础设施。
11. Binary Asset 使用 S3-compatible Object Storage。
12. Contract 使用 JSON Schema 2020-12 + OpenAPI 3.1。
13. OpenTelemetry 是统一遥测标准。
14. Local 使用 Docker Compose；单 CVM Stage 0仅按 ADR 0054 使用 Docker Compose；多实例高可用 Production 使用 Kubernetes + Helm + Terraform。
15. Exact Patch Version 由 lockfile / image digest 固定。
16. 修改本技术栈必须 ADR，不允许本地 AI 即兴换栈。
