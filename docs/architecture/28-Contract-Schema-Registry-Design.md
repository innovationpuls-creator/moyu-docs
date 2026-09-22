# Contract Schema Registry Design

> Status: Normative
>
> Canonical Owner: Command / Query / Event / Stream / Task / Error machine-readable contracts

## 1. 目标

此前架构文档已经定义了：

```text
Command
Query
Event
Stream
Error
Task
Identity
```

从本文件开始，这些稳定 Contract 不再只存在于 Markdown，自此建立：

```text
Machine-readable Contract Registry
```

用于：

```text
code generation
runtime validation
compatibility check
CI
frontend SDK
Python models
Realtime control frame
Event consumer
```

---

## 2. 基本原则

```text
Markdown
= 解释为什么和语义边界

Schema Registry
= 精确机器契约

Generated Code
= Schema 的语言投影
```

禁止：

```text
Markdown 一套字段
TypeScript 手写一套
Python 手写一套
Realtime 再写一套
```

## 2.1 Code Generation Source

代码生成的输入 Source 是：

```text
Contract Registry
```

Generator 必须遍历 `contracts/registry.yaml` 中注册的每一条 Contract，并按 `schemaPath` 读取其 Canonical JSON Schema；不得以 OpenAPI paths 是否引用某条 Contract 作为“是否生成”的判据。

推论：

```text
注册即生成
```

即任何 kind 的 Contract —— `Command` / `Query` / `Event` / `Error` / `Identity` —— 都必须在每种目标语言中存在正式投影。没有 HTTP Route 的 Contract（例如由 Realtime 通道承载的 Event）不得因此缺少 generated contract。

`contracts/openapi/client-api.yaml` 只描述 HTTP Client 面：Route、operationId、Header 与错误响应装配。它既是 HTTP 契约的 Canonical 描述，也是 HTTP 相关类型投影的输入之一，但不是 codegen 的根输入，也不构成“只在 OpenAPI 出现才算契约”的隐含规则。

```text
Contract Registry  →  语言投影（全部 kind）
OpenAPI Document   →  HTTP Route / Header / Response 装配
```

---

# Part A: Canonical Format

## 3. Payload Schema

普通业务 Payload 统一使用：

```text
JSON Schema 2020-12
```

---

## 4. HTTP Contract

官方客户端 API 使用：

```text
OpenAPI 3.1
```

OpenAPI 中的 Schema 应引用 Canonical JSON Schema，避免复制字段。

---

## 5. Event Contract

Event 使用：

```text
Event Registry Manifest
+
JSON Schema Payload
```

第一阶段不同时维护：

```text
Avro Schema Registry
Protobuf Schema Registry
```

---

## 6. WebSocket / Yjs 例外

WebSocket Control / System Frame 进入 Registry。

Yjs Sync / Update 本身继续保持：

```text
binary payload
```

Registry 只描述：

```text
frame type
routing fields
protocol version
watermark fields
payload kind
```

Yjs binary 内容由 `y-protocols` 负责，不转换成 JSON Schema 对象。

---

# Part B: Directory

## 7. Registry Layout

```text
contracts/
├── registry.yaml
├── registry-baseline.json
├── contract-ci.yaml
├── ids/
│   └── ids.schema.json
├── errors/
│   └── error-envelope.schema.json
├── commands/
├── queries/
├── events/
├── tasks/
├── streams/
├── realtime/
└── openapi/
    └── client-api.yaml
```

---

## 8. registry.yaml

每个 Contract 至少记录：

```text
logicalName
kind
domain
version
schema path
ownerDocument
ownerModule
status
```

`kind` 取值：

```text
Command
Query
Event
Error
Identity
```

`Error` 与 `Identity` 与 `Command` / `Query` / `Event` 同级：错误信封与 Canonical ID 类型同样是跨模块机器契约，必须有唯一注册位置，不得只作为某条 Command 的内嵌细节存在。

Command / Query 另外必须表达：

```text
requestRef          请求 Schema 指针；no-body 时记为 none
responseRef         响应 Schema 指针
requestBody         required / none
permissionCapability
authRequirement      Public / Authenticated / RecentAuthentication
idempotencyRequirement
errorCodes
```

`requestBody: none` 的 Command 表示该操作不携带请求体：客户端不得发送占位空对象，OpenAPI 中不得出现 `requestBody`，其 Canonical Schema 文件以 Response 为 root，从而生成物中只存在 Response 类型。这是唯一的 no-body 表达方式，不允许用“空对象 Schema”代替。

Event 另外必须表达 `eventSubject`，格式见 §25。

---

# Part C: Identity

## 9. Canonical ID Types

至少注册：

```text
UserId
WorkspaceId
ProjectId
FolderId
ResourceId
NodeId
TaskId
AttemptId
CommentId
ThreadId
AssetId
EventId
RequestId
OperationId
SessionId
SubscriptionId
DeliveryId
IdempotencyKey
```

---

## 10. UUIDv7

跨模块实体 ID：

```text
string
format: uuid
x-uuid-version: 7
```

不把数据库自增 ID 暴露成正式业务身份。

---

## 11. NodeRef

唯一稳定 Schema：

```text
NodeRef {
  resourceId
  nodeId
}
```

禁止重新出现：

```text
blockId
positionId
DOMPath
```

作为平行引用系统。

---

# Part D: Request Identity

## 12. requestId

语义：

```text
one concrete request attempt
```

重试时允许生成新的 `requestId`。

---

## 13. idempotencyKey

语义：

```text
one logical mutating command
```

安全 Retry：

```text
same idempotencyKey
```

不得和 `requestId` 混用。

---

## 14. Client Request Context

至少允许：

```text
requestId
clientVersion
traceparent
idempotencyKey when required
```

`userId / sessionId` 由服务端 Auth Context 得出，客户端提交的同名字段不构成权威身份。

---

# Part E: Command

## 15. Naming

Command 使用：

```text
VerbNoun
```

例如：

```text
CreateWorkspace
RenameResource
TrashResource
RestoreVersion
ApplyChangeSet
CancelTask
```

---

## 16. Command Schema

每个 Command 至少定义：

```text
logicalName
version
requestSchema
responseSchema
permissionCapability
idempotencyRequirement
errorCodes
```

---

## 17. Async Command

创建异步任务返回：

```text
TaskAccepted {
  taskId
  state
}
```

不能用 HTTP 200 暗示后台工作最终完成。

---

# Part F: Query

## 18. Naming

```text
Get...
List...
Search...
```

---

## 19. Query Schema

至少定义：

```text
request
response
filter
pagination
permission
errors
```

---

## 20. Pagination

列表优先：

```text
cursor pagination
```

统一响应：

```text
items
nextCursor
```

---

# Part G: Event

## 21. Naming

Event 必须使用已经发生的过去事实：

```text
ResourceCreated
ResourceTrashed
PermissionChanged
CommentCreated
TaskSucceeded
```

---

## 22. Event Envelope

统一：

```text
EventEnvelope {
  eventId
  eventType
  schemaVersion
  occurredAt
  producer
  traceId
  actorRef?
  workspaceId?
  resourceId?
  payload
}
```

---

## 23. Command 不是 Event

禁止：

```text
PleaseDeleteResource
DoApplyChange
```

作为 Event。

---

## 24. Event Version

Breaking Event Change：

```text
new major schemaVersion
```

兼容窗口结束前旧 Consumer 仍必须可工作或有明确 Migration Plan。

---

# Part H: NATS Subject

## 25. Event Subject

推荐稳定形式：

```text
event.<domain>.<logical-name>.v<major>
```

例如：

```text
event.resource.resource-trashed.v1
```

Subject 是 Transport Address，不是 Event Identity。

---

## 26. Task Subject

```text
task.<task-type>
```

例如：

```text
task.ai.generate
task.search.reindex
```

Task Queue Message 仍只是执行 Trigger。

---

# Part I: Error Registry

## 27. Top-level Category

固定：

```text
Validation
Authentication
Permission
NotFound
Conflict
RateLimit
Timeout
DependencyFailure
Unavailable
Internal
```

---

## 28. errorCode

Domain Error：

```text
SCREAMING_SNAKE_CASE
```

例如：

```text
SESSION_REPLACED
RESOURCE_TRASHED
PERMISSION_DENIED
CHANGESET_CONFLICT
COMMENT_ANCHOR_DETACHED
```

---

## 29. Error Envelope

```text
ErrorEnvelope {
  category
  errorCode
  messageKey
  requestId
  retryable
  fieldErrors?
  details?
}
```

---

## 30. messageKey

前端国际化使用：

```text
messageKey
```

业务逻辑不得依赖中文 / 英文错误文本。

---

## 31. details

只能返回安全的业务结构化信息。

禁止：

```text
stack trace
SQL
internal host
secret
provider token
```

---

# Part J: Task Registry

## 32. Task Type

每个 Task Type 定义：

```text
taskType
inputSchema
resultSchema
domainStageEnum
defaultPriority
retryPolicyName
cancelPolicy
permissionPolicy
handlerVersion
```

---

## 33. Generic Task State

只引用 `25-Async-Task-Execution-Design.md`：

```text
Created
Queued
Running
WaitingForUser
Retrying
Succeeded
PartialSucceeded
Failed
Cancelled
```

Domain Schema 不允许重新发明另一套 Generic State。

---

# Part K: Stream Registry

## 34. Stream Types

至少：

```text
ResourceEventStream
AccountEventStream
TaskStream
RealtimeResourceSync
AwarenessStream
```

---

## 35. Stream 不是任意 JSON 管道

Stream Payload 必须属于：

```text
registered Event
registered Progress
registered System Control Message
Yjs binary protocol payload
```

---

# Part L: WebSocket Frame Registry

## 36. Frame Classes

正式：

```text
Control
Sync
Awareness
System
```

---

## 37. Common Header

至少表达：

```text
protocolVersion
frameType
subscriptionId
resourceId when applicable
```

需要时包含：

```text
acceptedWatermark
durableWatermark
```

---

## 38. Binary Rule

`Sync / Yjs Update / Awareness` 的高频 Payload 保持 binary。

禁止：

```text
binary → Base64 → JSON → WebSocket
```

作为主链。

---

## 39. Watermark Contract

Registry 定义字段精确形状和版本。

语义 Owner：

```text
05 Realtime Protocol
06 Persistence
22 Feedback Flow
```

---

# Part M: OpenAPI

## 40. client-api.yaml

只描述：

```text
官方 Client API
```

第一版没有 Public Developer API。

---

## 41. operationId

每个 HTTP Operation 的 `operationId` 必须稳定映射到 Canonical Command / Query Name。

例如：

```text
POST /v1/resources/{resourceId}:trash
operationId: TrashResource
```

URL 可以演进，logical operation 名不能随意漂移。

---

# Part N: TypeScript Generation

## 42. Generated Package

输出：

```text
packages/ts/contracts
```

生成集由 `registry.yaml` 决定：注册的每条 Contract 的每个 kind 都要有 TypeScript 投影，包括没有 HTTP Route 的 Event / Error / Identity。生成物按 Canonical 目录结构投影，禁止手改。

---

## 43. HTTP

使用：

```text
openapi-typescript
```

生成 OpenAPI Type。

统一 Client：

```text
openapi-fetch
```

---

## 44. Non-HTTP JSON Schema

Event / Task / Realtime Control 类型使用：

```text
json-schema-to-typescript
```

生成 TS Types。

---

## 45. Runtime

使用：

```text
Ajv
```

验证不可信 / 跨进程数据。

---

# Part O: Python Generation

## 46. Generated Package

输出：

```text
packages/py/contracts
```

生成集由 `registry.yaml` 决定：注册的每条 Contract 的每个 kind 都要有 Python 投影，包括没有 HTTP Route 的 Event / Error / Identity。生成物按 Canonical 目录结构投影，禁止手改。

---

## 47. Generator

使用：

```text
datamodel-code-generator
```

生成 Pydantic v2 Models。

---

## 48. 禁止双份 DTO

如果一个 Request / Event 已在 Registry：

```text
FastAPI Route
Worker
Consumer
```

不得重新手写另一份同名模型作为真相。

---

# Part P: Compatibility

## 49. Non-breaking

通常包括：

```text
新增 optional field
新增 Event type
新增 Error code
```

仍需 Contract Test。

---

## 50. Breaking

包括：

```text
删除 required field
改变 field meaning
optional → required
type changed
enum value removed
```

必须发布新 Major Schema Version。

---

## 51. Consumer Compatibility

Event Release Gate 至少检查：

```text
new producer
current consumer
previous supported consumer
```

---

# Part Q: Deprecation

## 52. Status

```text
active
deprecated
removed
```

---

## 53. Deprecated

兼容窗口内继续工作，但 Codegen / CI 可以 Warning。

---

## 54. Removed

仅在：

```text
所有调用者迁移完成
兼容窗口结束
```

后允许删除。

---

# Part R: CI

## 55. Contract CI

必须执行：

```text
schema syntax validation
reference resolution
duplicate logical name check
duplicate event subject check
errorCode uniqueness
OpenAPI validation
breaking change detection
code generation
generated drift check
consumer contract tests
```

### 55.1 Breaking Change Baseline

Breaking Change Detection 以已验证的基线为参照：

```text
contracts/registry-baseline.json
```

基线保存每条 Contract 的结构指纹（kind、eventSubject、version major、request/response 的字段类型、required 集合与 enum 取值集合）。CI 用当前 Registry 与该基线比对，出现 §50 定义的 Breaking 变化即失败；§49 允许的非破坏性变化通过但需更新基线。

基线只能由显式命令重建，且重建本身必须表现为一次可见的提交差异，不允许 CI 静默改写基线。

### 55.2 Obligation Registry

每条 CI 义务的当前状态与证据记录在：

```text
contracts/contract-ci.yaml
```

状态取值：

```text
enforced        已有自动化实现（必须给出可执行的 evidence 路径）
not-applicable  当前确实不适用（必须给出 reason 与 mandatoryWhen 触发条件）
```

`not-applicable` 只允许是临时状态。`Consumer Contract Test` 在出现第一个真实 Consumer 之前记为 `not-applicable`；一旦存在 Consumer，该义务自动转为 `enforced`，且必须同时存在对应测试。

---

## 56. Generated Drift

CI 执行 Codegen 后：

```text
git diff must be clean
```

防止 Schema 改了而生成物没更新。

---

# Part S: Security Metadata

## 57. Sensitive Field

Schema 可以标记：

```text
x-sensitive: true
```

用于：

```text
log redaction
telemetry suppression
documentation warning
```

---

## 58. Secret 禁止传播

以下默认不能出现在普通 Event / Task Payload：

```text
password
session credential
OAuth code
access token
provider secret
webhook secret
signed URL full value
```

---

# Part T: Ownership

## 59. Registry 与 Domain Docs

```text
Domain Architecture
→ owns semantic meaning

Contract Registry
→ owns exact machine shape
```

两者不一致时必须修复，不允许实现者自行选一边。

---

## 60. Constitution

`00-ARCHITECTURE-CONSTITUTION.md` 仍是最高级规则。

Registry 不得通过“Schema 已经这样写了”绕过 Constitution。

---

# Part U: Hard Constraints

## 61. 架构硬约束

1. 普通业务 Payload Canonical Machine Schema 使用 JSON Schema 2020-12。
2. 官方 Client HTTP Contract 使用 OpenAPI 3.1。
3. Command / Query / Event / Task / Error / Stream Control 全部进入 Registry。
4. WebSocket 上 Yjs Update 保持 Binary。
5. `requestId` 与 `idempotencyKey` 是不同类型和语义。
6. Event 必须过去事实命名并可版本化。
7. Error Category 只能使用 Constitution 定义的十类。
8. `errorCode` 稳定且唯一。
9. Generic Task State 只引用 25。
10. TypeScript / Python Contract Type 必须生成。
11. Generated Code 不允许手改。
12. CI 必须检测 Breaking Change 和 Generated Drift。
13. Secret / Password / Token 不进入普通跨模块 Payload。
14. 本地 AI 新增跨模块 DTO 前，必须先更新 Registry。
