# DOM 后端 → 前端接口参考（API Reference）

> 用途：给前端实现与 UI/UX 设计使用的**能力面完整清单**。UI/UX 只需按
> 能力层理解（`19-Frontend-Module-Contract-Design.md §111/§112`），不需要
> 记忆路径——本文件列出路径只为方便对照与实现。
>
> **权威来源**（本文件是对它们的整理，改接口以源头为准）：
>
> - REST 契约面：`contracts/registry.yaml` + `contracts/openapi/client-api.yaml`（生成产物）
> - REST 运行面：`services/api/src/api/routes/*`（`main.py` 挂载）
> - 实时协议：`services/realtime/src/server/websocket_server.ts`、`packages/ts/realtime-client`（前端唯一 WS 入口）
> - 前端调用纪律：`apps/web` 经 `client-sdk / realtime-client` 访问，禁止直接 `fetch` / `new WebSocket`（`27` §13、`00` §47）

---

## 1. 通道与基本信息

| 项 | 值 |
|---|---|
| REST 基址（dev） | `http://127.0.0.1:8000` |
| REST 基址（prod，OAS `servers`） | `https://api.dom.internal` |
| Realtime 网关（dev） | `ws://localhost:8765/v1/realtime`（默认；可用 `VITE_REALTIME_URL` 覆盖） |
| REST 认证 | HttpOnly Cookie：`dom_session`（会话）+ `dom_device`（设备），`SameSite=Lax`；`login` 时下发 |
| Realtime 认证 | WS 升级握手携带 `dom_session` Cookie，对 Valkey 会话缓存验签（失败 → HTTP 401，客户端表现为 `unexpected-response`） |
| 机器接口认证 | Ed25519 请求签名头（见 §5），**非浏览器 UI 使用** |
| 成功响应 | 直接 JSON body（无统一包裹） |
| 错误响应 | 统一 `ErrorEnvelope`（见 §6） |

端口来源：`services/realtime` 默认 `REALTIME_API_BASE_URL=http://127.0.0.1:8000`（API dev 端口）；
`apps/web/src/pages/editor.ts` 默认实时 URL 见上表。

---

## 2. 认证与会话（所有用户端 REST 端点统一规则）

- 除 §5「机器接口」与 `/v1/auth/*` 免登录端点外，其余端点均要求有效 `dom_session`。
- 会话可撤销：第三方登录会替换旧设备会话；被替换的连接会被实时网关强制断开（close code `4001`，见 §4）。
- 敏感操作（删除账号等）要求 `Reauthenticate`（FR-AUTH-034）。
- 端点级速率限制：`/v1/public/*` 默认 `120` 次/窗口（env `PUBLIC_RATE_LIMIT`），超限返回 429 `RATE_LIMITED`。

---

## 3. REST 端点总表

契约状态标注：**【注册】** = 在 `contracts/openapi/client-api.yaml`（有 client 契约与生成类型，前端应优先使用）；
**【API 层】** = 存在于运行面与代码、未注册 client 契约（无生成类型，形态可能变动）。

### 3.1 认证与账户（14 个注册 ▪ 前端模块 01 Auth / 23 Account-Security）

| 方法 | 路径 | LogicalName | 说明 | 前端模块 |
|---|---|---|---|---|
| POST | `/v1/auth/register` | RegisterWithEmail | 邮箱+密码注册，签发会话 | 01 |
| POST | `/v1/auth/verify-email` | VerifyEmail | 验证邮箱（一次性 token） | 01 |
| POST | `/v1/auth/resend-verification` | ResendEmailVerification | 重发验证邮件 | 01 |
| POST | `/v1/auth/login` | LoginWithPassword | 邮箱+密码登录 | 01 |
| POST | `/v1/auth/logout` | Logout | 登出当前设备会话 | 23 |
| GET | `/v1/auth/me` | GetCurrentAccount | 当前账号信息 | 23 |
| GET | `/v1/auth/session` | GetCurrentSession | 当前设备会话信息 | 23 |
| POST | `/v1/auth/forgot-password` | RequestPasswordReset | 请求密码重置 | 01 |
| POST | `/v1/auth/reset-password` | ResetPassword | 用一次性 token 重置密码 | 01 |
| POST | `/v1/auth/reauthenticate` | Reauthenticate | 高危操作前重新验证密码 | 23 |
| POST | `/v1/auth/delete-account` | RequestAccountDeletion | 申请删除账号（30 天宽限） | 23 |
| POST | `/v1/auth/cancel-delete-account` | CancelAccountDeletion | 取消删除 | 23 |
| GET | `/v1/auth/status` | GetAccountStatus | 账号生命周期状态+删除窗口 | 23 |
| GET | `/v1/auth/my-workspace-ownership` | HasSoleWorkspaceOwnership | 是否唯一 Workspace Owner | 23/19 |

### 3.2 Workspace / Project / Folder 生命周期（19 个注册 ▪ 前端模块 02/03/04/05/19）

| 方法 | 路径 | LogicalName | 说明 | 前端模块 |
|---|---|---|---|---|
| POST | `/v1/workspaces` | CreateWorkspace | 创建 Workspace 并请求初始 Owner bootstrap | 02 |
| GET | `/v1/workspaces` | ListWorkspaces | 当前账号可见的 Workspace 列表 | 02 |
| GET | `/v1/workspaces/{workspaceId}` | GetWorkspace | Workspace 元数据 | 02/05 |
| PATCH | `/v1/workspaces/{workspaceId}` | RenameWorkspace | 重命名（同级重名校验） | 02 |
| POST | `/v1/workspaces/{workspaceId}/projects` | CreateProject | 创建 Project | 03 |
| GET | `/v1/workspaces/{workspaceId}/projects` | ListProjects | Project 列表 | 03 |
| POST | `/v1/workspaces/{workspaceId}/owner` | TransferWorkspaceOwner | 转移 Workspace Owner | 19 |
| GET | `/v1/projects/{projectId}` | GetProjectTree | 项目树（仅元数据） | 03/04 |
| PATCH | `/v1/projects/{projectId}` | RenameProject | 重命名 Project | 03 |
| POST | `/v1/projects/{projectId}/archive` | ArchiveProject | 归档（只读元数据） | 03 |
| POST | `/v1/projects/{projectId}/unarchive` | UnarchiveProject | 取消归档 | 03 |
| POST | `/v1/projects/{projectId}/trash` | TrashProject | 整子树进回收站 | 03/24 |
| POST | `/v1/projects/{projectId}/restore` | RestoreProject | 整子树恢复 | 03/24 |
| POST | `/v1/projects/{projectId}/folders` | CreateFolder | 创建 Folder | 04 |
| GET | `/v1/projects/{projectId}/folders` | ListFolderChildren | Folder 直接子级 | 04 |
| PATCH | `/v1/folders/{folderId}` | RenameFolder | 重命名 Folder | 04 |
| POST | `/v1/folders/{folderId}/move` | MoveFolder | 同 Project 内移动 | 04 |
| POST | `/v1/folders/{folderId}/trash` | TrashFolder | Folder 子树进回收站 | 04/24 |
| POST | `/v1/folders/{folderId}/restore` | RestoreFolder | Folder 子树恢复（根回退+安全命名） | 04/24 |

### 3.3 资源与编辑器（9 个注册 + 3 个 API 层 ▪ 前端模块 05/06/08/09/24/22）

| 方法 | 路径 | LogicalName | 说明 | 前端模块 |
|---|---|---|---|---|
| POST | `/v1/resources` | CreateResource | 在 Project 下创建资源 | 05 |
| POST | `/v1/resources/{resourceId}/journal` | AppendJournalOp | 追加一条内容 op（journal 源真相） | 06/09 |
| GET | `/v1/resources/{resourceId}` | OpenResource | 资源元数据+最新快照 | 05/06 |
| PATCH | `/v1/resources/{resourceId}` | RenameResource | 重命名资源 | 05 |
| POST | `/v1/resources/{resourceId}/restore` | RestoreResource | 回收站 → Active | 24 |
| POST | `/v1/resources/{resourceId}/trash` | TrashResource | 资源进回收站 | 24 |
| GET | `/v1/projects/{projectId}/resources` | ListResources | Project 资源列表 | 05 |
| GET | `/v1/resources/{resourceId}/export` | ExportResource | 导出为版本化交换文档 | 18 |
| POST | `/v1/resources/{resourceId}/import` | ImportResource | 导入交换文档 | 17 |
| GET | `/v1/resources/{resourceId}/diff`【API 层】 | — | 版本间内容 diff（无 client 契约） | 13 |
| POST | `/v1/resources/{resourceId}/assets`【API 层】 | — | 上传附件（multipart） | 16 |
| GET | `/v1/assets/{assetId}`【API 层】 | — | 下载/预览附件 | 16 |

### 3.4 评论 / 提及（5 个注册 ▪ 前端模块 10）

| 方法 | 路径 | LogicalName | 说明 | 前端模块 |
|---|---|---|---|---|
| POST | `/v1/resources/{resourceId}/comments` | AddComment | 追加扁平评论（anchor 可选） | 10 |
| GET | `/v1/resources/{resourceId}/comments` | ListComments | 评论列表 | 10 |
| PATCH | `/v1/comments/{commentId}` | EditComment | 作者编辑正文 | 10 |
| DELETE | `/v1/comments/{commentId}` | DeleteComment | 作者软删除 | 10 |
| GET | `/v1/workspaces/{workspaceId}/members/suggest` | SuggestMembers | @提及自动补全成员（FR-NTF-004） | 10 |

### 3.5 通知（3 个注册 ▪ 前端模块 11）

| 方法 | 路径 | LogicalName | 说明 | 前端模块 |
|---|---|---|---|---|
| GET | `/v1/notifications` | ListNotifications | 站内通知（最新在前） | 11 |
| POST | `/v1/notifications` | MarkNotificationsRead | 全部已读 | 11 |
| POST | `/v1/notifications/{notificationId}/read` | MarkNotificationRead | 单条已读 | 11 |

### 3.6 搜索（5 个注册 ▪ 前端模块 12）

| 方法 | 路径 | LogicalName | 说明 | 前端模块 |
|---|---|---|---|---|
| GET | `/v1/workspaces/{workspaceId}/search` | SearchWorkspace | 资源名/正文检索 | 12 |
| GET | `/v1/workspaces/{workspaceId}/search/suggestions` | SearchSuggestions | 语料前缀建议 | 12 |
| GET | `/v1/workspaces/{workspaceId}/search/comments` | SearchComments | 评论正文检索 | 12 |
| GET | `/v1/search/history` | SearchHistory | 最近查询历史 | 12 |
| DELETE | `/v1/search/history` | ClearSearchHistory | 清空查询历史 | 12 |

### 3.7 历史 / 版本（3 个注册 ▪ 前端模块 13）

| 方法 | 路径 | LogicalName | 说明 | 前端模块 |
|---|---|---|---|---|
| GET | `/v1/resources/{resourceId}/history` | ListVersions | 版本时间线 | 13 |
| POST | `/v1/resources/{resourceId}/history` | RestoreVersion | 恢复到某版本 = 新当前 | 13 |
| POST | `/v1/resources/{resourceId}/versions` | CreateNamedVersion | 给修订打命名版本 | 13 |

### 3.8 AI 变更集（2 个 API 层 ▪ 前端模块 14/15）

| 方法 | 路径 | LogicalName | 说明 | 前端模块 |
|---|---|---|---|---|
| POST | `/v1/ai/propose-changeset`【API 层】 | — | AI 提议变更集（未注册 client 契约） | 14 |
| POST | `/v1/changesets/{changesetId}/apply`【API 层】 | — | 应用变更集（正式 Apply 必经后端） | 15 |

> 约束：AI UI 可设计 Diff Panel / Review Screen，但正式 Apply 必须经
> ChangeSet + 后端操作（`19` §117）。

### 3.9 运维 / 诊断（1 个注册 + 2 个 API 层 ▪ 非产品 UI）

| 方法 | 路径 | LogicalName | 说明 | 归属 |
|---|---|---|---|---|
| GET | `/v1/ops/metrics` | GetOpsMetrics | 进程内运维指标（OPS-001） | 运维 |
| GET | `/v1/health`【API 层】 | — | 存活探针 | 运维 |
| GET | `/v1/diagnostics`【API 层】 | — | 诊断信息 | 运维 |

---

## 4. Realtime WebSocket 协议（arch `05`）

### 4.1 连接

- URL：`ws://<api-host>/v1/realtime`（dev 默认 `ws://localhost:8765/v1/realtime`）
- 认证：升级握手带 `dom_session` Cookie；验签失败 → 401（浏览器端表现为 `unexpected-response`）
- 会话被替换：网关先发 `SessionReplaced` 控制帧，随后以 **close code 4001** 断开（`SESSION_REPLACED_CLOSE_CODE`）；前端经 `@dom/realtime-client` 的 `onSessionReplaced` / `sessionreplaced` 事件处理，勿自行解析 socket
- 其他 close code：`4400` 消息畸形、`4401` 缺会话、`1001` 服务端关停

### 4.2 客户端 → 服务端消息（JSON）

| type | resourceId | payload | 语义 |
|---|---|---|---|
| `subscribe` | ✓ | `{}` | 订阅资源频道；成功 → 广播 roster；无权限 → 回 `{kind:"subscribe", payload:{status:"denied"}}` |
| `unsubscribe` | ✓ | `{}` | 退订 |
| `op` | ✓ | `{kind:"yjs", update:<base64>}` | Yjs 更新，转发给**其他**订阅者，并写入 backlog |
| `op` | ✓ | `{kind:"sync", stateVector:<base64>}` | 增量同步请求：网关合并 backlog 后回**一条** `yjs` op（state-vector 差量） |
| `op` | ✓ | `{kind:"awareness", update:<base64>}` | awareness 更新（光标/选中），原样 peer 转发 |
| `op` | ✓ | `{kind:"presence", typing, peerId, cursor?}` | 编辑在场状态（typing + 光标位置），peer 用于展示"正在编辑/光标" |

### 4.3 服务端 → 客户端信封（JSON）

统一 `{resourceId, kind, payload, occurredAt?}`（客户端映射为 `type`）：

| kind | payload | 语义 |
|---|---|---|
| `op` | `{kind:"yjs", update}` | 远端 Yjs 更新（含增量同步回包） |
| `op` | `{kind:"roster", peers}` | 订阅者名单广播（join/leave 时） |
| `op` | `{kind:"presence", typing, peerId, cursor?}` | peer 在场状态 |
| `op` | `{kind:"awareness", update}` | peer awareness 更新 |
| `presence` | `{room, actorId, kind:"join"|"leave", occurredAt}` | presence 注册表事件 |
| `subscribe` | `{status:"denied"}` | 订阅被拒（无权限） |
| `comment.added` / `comment.edited` / `comment.deleted` | `{body?, …}` | 评论实时事件（best-effort） |
| `SessionReplaced` | `{type:"SessionReplaced", reason, message}` | 控制帧（随后 close 4001） |

**前端纪律**：`new WebSocket` 只允许出现在 `packages/ts/realtime-client`；feature 页经
`connectRealtime` / `ResourceChannelClient`（`publishOp` / `publishSync` /
`publishAwareness` / `subscribe` / `unsubscribe` / `getClientId`）使用。

---

## 5. 机器接口（非浏览器 UI）

以下端点供外部系统/集成使用，**不是 Web UI 的功能面**（UI/UX 无需设计）：

| 方法 | 路径 | 逻辑名 | 认证 |
|---|---|---|---|
| GET | `/v1/public/notifications` | GetPublicNotifications | Ed25519 签名头（见下） |
| GET | `/v1/public/resources` | GetPublicResources | Ed25519 签名头 |
| GET | `/v1/integrations/usage` | GetApiUsage | Ed25519 签名头 |
| POST | `/v1/integrations/api-keys/{keyId}/rotate` | RotateApiKey | Ed25519 签名头 |
| POST | `/v1/webhooks/{webhookId}/deliveries/requeue` | RequeueWebhookDeliveries | 管理面 |
| POST | `/v1/workspaces/{workspaceId}/webhooks` | RegisterWebhook | 管理面 |
| GET | `/v1/workspaces/{workspaceId}/webhooks` | ListWebhooks | 管理面 |
| POST | `/v1/workspaces/{workspaceId}/webhooks/{subscriptionId}/test` | TestWebhook | 管理面 |
| DELETE | `/v1/workspaces/{workspaceId}/webhooks/{subscriptionId}` | RemoveWebhook | 管理面 |

Ed25519 签名头：`X-Dom-Key-Id` / `X-Dom-Signature` / `X-Dom-Timestamp`（300 秒时间窗）。
Webhook 事件经 NATS 入队、worker 投递，带密钥签名与有界重试（见 `10`、`14`、`23`）。

---

## 6. 错误信封（`ErrorEnvelope`，doc `28` §28–§31/§55）

所有错误响应统一结构：

```json
{
  "category": "Validation|Authentication|Permission|NotFound|Conflict|RateLimit|Timeout|DependencyFailure|Unavailable|Internal",
  "errorCode": "RATE_LIMITED",
  "messageKey": "RATE_LIMITED",
  "message": "human readable",
  "requestId": "uuid",
  "retryable": false,
  "fieldErrors": [ {"field": "...", "code": "..."} ],
  "details": {}
}
```

HTTP 语义映射（Constitution §3.19）：Validation→422、Authentication→401、Permission→403、
NotFound→404、Conflict→409、RateLimit→429、Timeout→504、DependencyFailure→502、
Unavailable→503、其他→500。`errorCode` 目录权威在 `contracts/errors/error-codes.yaml`。

---

## 7. 权威文件与验证

| 面 | 权威文件 |
|---|---|
| 契约注册 | `contracts/registry.yaml`（82 个 logicalName）、`contracts/contract-ci.yaml` |
| 生成的 OpenAPI | `contracts/openapi/client-api.yaml`（68 个端点，本文件 §3【注册】行即源于此） |
| 生成的 TS 类型 | `packages/ts/contracts`（**生成物禁止手改**） |
| 生成的 Python 类型 | `packages/py/contracts`（**生成物禁止手改**） |
| 错误码 | `contracts/errors/error-codes.yaml` |
| 验证 | `just check-full`：契约 52 项 + `generate_contracts.py --check`（无 drift）+ 路由回归 |

---

## 8. 前端使用纪律（提醒）

- Feature 不直接 `fetch`、不自行创建 WebSocket；一律经 `client-sdk` / `realtime-client`（`27` §13、`00` §47）。
- UI/UX 以**能力层**设计（`Create Comment` / `Reply` / `Resolve`），不绑定接口名/路径（`19` §112）。
- UI 不得自行定义一致性语义、权限、离线合并规则——状态语义来自系统契约（`19` §113–§118）。
- 本文件【API 层】端点无生成类型，前端使用前应在 `contracts/registry.yaml` 注册（走 Contract CI），避免形态漂移。