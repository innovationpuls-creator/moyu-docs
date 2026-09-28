# API Gateway & External Integration Design

## 1. 目标

本设计定义系统对外入口、官方客户端 API Gateway、第三方身份回调、Webhook、邮件服务、外部 Provider Adapter、失败隔离、重试、限流、安全校验和可观测性边界。

本模块解决：

> 外部流量从哪里进入系统，官方前端如何进入后端，微信 / 飞书 OAuth Callback 如何与普通业务 API 隔离，Webhook 如何安全接收和投递，邮件如何可靠发送，外部 Provider 故障时如何避免拖垮核心协作链路，以及所有第三方能力如何通过统一 Adapter 接入而不是散落在业务代码中。

本设计按正式生产环境标准设计。

---

## 2. 模块定位

系统中的“外部交互”统一分为四类：

```text
Official Client Traffic
Provider Callback
Webhook
Outbound Provider Call
```

分别对应：

```text
官方 Web / Mobile Companion
微信 / 飞书 OAuth Callback
第三方事件推送 / 未来系统 Webhook
邮件 / AI / 对象存储 / 第三方 API
```

它们都属于 External Integration Boundary。

---

## 3. 总体架构

```text
Internet
   │
   ▼
Edge / Load Balancer
   │
   ├── Client API Gateway
   │      ├── Command
   │      ├── Query
   │      └── Auth / Session
   │
   ├── Realtime Gateway
   │      └── WebSocket / Yjs Stream
   │
   ├── Provider Callback Gateway
   │      ├── WeChat Callback
   │      └── Feishu Callback
   │
   └── Webhook Receiver
          └── Verified External Events
                 │
                 ▼
            Integration Layer
                 │
       ┌─────────┼─────────┐
       ▼         ▼         ▼
 Provider Adapter Email Adapter Webhook Adapter
       │         │         │
       ▼         ▼         ▼
   External Providers / Services
```

---

## 4. Gateway 不是业务中心

Gateway 负责：

```text
Authentication
Rate Limit
Request Validation
Protocol Version
Request Size Limit
Routing
Tracing
Error Normalization
Security Boundary
```

Gateway 不负责：

```text
Resource Business Logic
Permission Rule Definition
History Logic
Comment Logic
AI Planning
Persistence Logic
```

不能演化成：

```text
God Gateway
```

---

## 5. Gateway 分层

建议逻辑分成：

```text
Edge Gateway
Client API Gateway
Realtime Gateway
Provider Callback Gateway
Webhook Receiver
```

不要求部署成五个独立进程。

第一版可以共享部分基础设施。

但逻辑边界必须存在。

---

## 6. Edge Gateway

Edge 负责：

```text
TLS Termination
Basic DDoS Protection
Connection Limit
IP Reputation / WAF（如果部署环境提供）
Request Size Limit
Routing
Health Check
```

具体产品由部署环境决定。

---

## 7. Client API Gateway

只服务：

```text
官方客户端
```

第一版不作为：

```text
Public Developer API
```

入口。

它承接：

```text
Command
Query
Session
Account
Workspace
Project
Resource Metadata
Comment
Notification
Search
History
AI Task
Asset Control Plane
Import / Export Control Plane
```

---

## 8. Realtime Gateway

Realtime Gateway 只处理：

```text
WebSocket
Resource Subscription
Yjs Sync
Awareness
Resource Event Stream
Account Event Stream
Task Stream
```

不承载：

```text
大文件上传
完整 Import ZIP
Export Binary
普通大 Query
```

避免实时链路被大流量业务拖慢。

---

## 9. Provider Callback Gateway

Provider Callback Gateway 专门处理：

```text
微信
飞书
```

授权回调。

它与普通 Client API 路径分离。

原因：

```text
Callback 有独立的安全验证
Callback 是 Provider 主动返回
Callback 可能没有现成 Session
Callback 有独立限流和错误模型
```

---

## 10. Webhook Receiver

Webhook Receiver 专门接收：

```text
第三方系统主动推送的事件
```

第一版主要用于：

```text
系统自有第三方 Provider
```

例如未来：

```text
支付
文件扫描
异步媒体处理
企业集成
```

第一版不开放：

```text
用户自由配置任意公开 Webhook Endpoint
```

---

## 11. 第一版 Public API 边界

第一版明确：

```text
No Public API
No Developer Token
No Public Webhook Platform
```

但系统内部必须把：

```text
Gateway
Provider Adapter
Webhook Adapter
```

设计成可扩展架构。

未来开放开发者平台时：

```text
不需要重写核心业务模块
```

---

# Part A: Client API Gateway

## 12. Client Request Context

Gateway 为每个请求建立：

```text
requestId
traceId
clientVersion
userId（如已登录）
sessionId（如已登录）
workspaceId（如适用）
projectId（如适用）
resourceId（如适用）
```

下游模块复用这一 Context。

---

## 13. 身份验证

Gateway 负责：

```text
验证 Session Credential
```

但不负责：

```text
计算完整业务 Permission
```

身份验证得到：

```text
Actor
```

权限由：

```text
Permission Module
```

决定。

---

## 14. 匿名请求

允许匿名进入的路径必须显式 Allowlist。

例如：

```text
Register
Login
Password Reset
Email Verification
WeChat Start / Callback
Feishu Start / Callback
Anonymous Share Read
Health（按策略）
```

其他路径默认：

```text
Require Auth
```

---

## 15. Fail Closed

身份或安全状态无法确认时：

```text
高风险写操作
```

必须：

```text
Fail Closed
```

不能因为 Auth / Permission Cache 异常：

```text
默认放行
```

---

## 16. Request Validation

Gateway / Contract Layer 至少校验：

```text
schema
required field
enum
payload size
content type
protocol version
```

业务语义仍由对应 Domain Service 校验。

---

## 17. Payload Size

不同入口必须有不同大小限制。

例如：

```text
普通 Command / Query
→ 小 Payload

Comment
→ 有内容上限

Import Metadata
→ 小 Payload

Asset Binary
→ 不走普通 JSON Gateway
```

不能一个全局巨大限制解决所有场景。

---

## 18. Binary Data

大文件：

```text
Asset
Import Source
Export Result
```

不通过 Client API Gateway 转发完整二进制。

采用：

```text
Control Plane
+
Object Storage Data Plane
```

---

## 19. Rate Limit

Gateway 至少支持：

```text
IP limit
Session limit
Account limit
Workspace limit
Operation-specific limit
```

不同业务独立。

例如：

```text
Login
Search
Comment
AI Task
Import
```

不能共享一个简单全局 QPS。

---

## 20. Rate Limit Key

不能只依赖：

```text
IP
```

因为：

```text
NAT
校园网
企业出口
VPN
```

可能共享地址。

需要组合：

```text
IP
Account
Session
Operation
Workspace
```

---

## 21. Error Normalization

客户端只接收统一：

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

Provider 原始错误：

```text
不能直接透传到客户端
```

---

## 22. Provider Error Mapping

例如：

```text
WeChat invalid code
Feishu provider unavailable
Email provider timeout
```

统一转成系统：

```text
ProviderAuthFailed
ProviderUnavailable
EmailDeliveryUnavailable
```

同时内部保留 Provider Diagnostic。

---

# Part B: 微信 / 飞书 OAuth Callback

## 23. Provider Adapter

微信和飞书通过统一：

```text
Auth Provider Adapter
```

接入。

业务 Account 模块不能直接包含：

```text
微信 HTTP 调用
飞书 HTTP 调用
Provider JSON Parsing
```

---

## 24. Adapter Contract

Provider Adapter 至少提供：

```text
BuildAuthorizationRequest
ValidateCallback
ExchangeAuthorizationCode
FetchProviderIdentity
NormalizeIdentity
RefreshProviderCredential（仅未来需要时）
RevokeProviderCredential（如 Provider 支持且确有需要）
```

---

## 25. Provider Identity Normalize

不同 Provider 返回字段不同。

统一转换为：

```text
provider
providerSubject
verified attributes
display metadata
provider tenant context（如确有需要）
```

Account Service 只消费 Normalize 后的数据。

---

## 26. Provider Callback State

OAuth 发起时生成：

```text
state
```

Callback 时必须验证。

用于防止：

```text
CSRF
Login Confusion
Callback Forgery
```

---

## 27. PKCE / Nonce

如果 Provider 和 Flow 支持：

```text
PKCE
nonce
```

应优先采用成熟安全方式。

具体能力根据微信 / 飞书当前开放接口实现。

---

## 28. Authorization Code

Authorization Code：

```text
短期
单次
```

Callback Handler 不能：

```text
长期保存
写普通日志
返回给前端业务页面
```

---

## 29. Callback Redirect

登录完成后跳转目标：

```text
returnTo
```

必须通过：

```text
Internal Route Allowlist
```

验证。

禁止：

```text
任意外部 URL Redirect
```

---

## 30. Provider Secret

微信 / 飞书：

```text
App Secret
Client Secret
```

只存：

```text
Secret Manager
```

禁止：

```text
前端
Git
普通 Config
普通日志
```

---

## 31. Callback Idempotency

Provider Callback 可能：

```text
浏览器重试
重复跳转
网络重放
```

系统必须防止：

```text
重复创建 Account
重复绑定 Identity
重复创建多个 Active Session
```

---

## 32. Provider Identity Conflict

同一个：

```text
provider + providerSubject
```

必须唯一绑定一个 Account。

使用：

```text
PostgreSQL Unique Constraint
```

保证。

---

## 33. Provider Callback Rate Limit

Callback Endpoint 也必须：

```text
限流
```

不能认为：

```text
“只有 Provider 会访问”
```

攻击者同样可以直接请求 URL。

---

## 34. Provider Callback Logging

允许记录：

```text
provider
result
error code
requestId
traceId
duration
```

禁止记录：

```text
authorization code
access token
refresh token
client secret
完整用户敏感信息
```

---

# Part C: Webhook Receiver

## 35. Webhook 定位

Webhook 表示：

> 外部系统主动把已经发生的事件推送给本系统。

Webhook 不是：

```text
普通 Query
```

也不是：

```text
客户端 Command
```

---

## 36. Webhook Receiver Pipeline

标准流程：

```text
Receive Raw Request
↓
Validate Source
↓
Verify Signature
↓
Verify Timestamp / Replay Window
↓
Parse Event
↓
Deduplicate
↓
Persist Receipt / Inbox
↓
Return Provider ACK
↓
Async Process
```

---

## 37. 快速 ACK

Webhook Receiver 不应在 HTTP 请求内完成：

```text
复杂业务
AI
大量数据库处理
媒体处理
```

验证并可靠接收后：

```text
快速 ACK
```

业务进入异步处理。

避免 Provider 因超时不断重试。

---

## 38. Raw Body

如果 Provider Signature 基于原始 Body：

```text
必须保留 Raw Body
```

直到签名验证完成。

不能：

```text
先 JSON Parse 再重新序列化
```

然后验证签名。

---

## 39. Signature Verification

每个 Provider Adapter 定义自己的：

```text
signature algorithm
header
secret
timestamp rule
```

Webhook Receiver 提供统一框架。

禁止业务模块自己散落实现验签。

---

## 40. Replay Protection

至少结合：

```text
timestamp
eventId
nonce
dedup key
```

防止攻击者把合法旧 Webhook 重放。

---

## 41. Webhook Inbox

可靠接收建议使用：

```text
Webhook Inbox
```

或等价模型保存：

```text
provider
eventId
receivedAt
status
attempt
payload reference / sanitized payload
```

---

## 42. Webhook Idempotency

同一个 Provider Event：

```text
重复投递
```

必须：

```text
只产生一次业务效果
```

Provider 的：

```text
at-least-once
```

不能传染成业务重复。

---

## 43. Unknown Event

Provider 发送未知 Event Type：

```text
不能崩溃
```

应：

```text
记录
安全忽略
或进入 Unsupported 状态
```

---

## 44. Webhook Schema Version

Provider Payload 可能升级。

Adapter 必须处理：

```text
schema version
unknown field
optional field
```

不能把 Provider JSON 结构直接泄漏进 Domain Model。

---

## 45. Webhook Secret Rotation

Webhook Secret 必须支持：

```text
rotation
```

轮换期间可以短时间接受：

```text
current secret
previous secret
```

避免切换瞬间丢事件。

---

# Part D: Outbound Webhook

## 46. 第一版 Outbound Webhook

第一版不向普通用户开放：

```text
自定义 Webhook URL
```

但架构保留：

```text
Outbound Webhook Adapter
```

用于未来：

```text
企业集成
Developer Platform
Automation
```

---

## 47. Outbound Webhook Event

未来开放时：

```text
Internal Event
↓
Webhook Delivery
↓
External Endpoint
```

不能让业务模块直接：

```text
HTTP POST 用户 URL
```

---

## 48. Delivery Semantics

Outbound Webhook 采用：

```text
At-least-once Delivery
```

外部消费者必须依赖：

```text
eventId
```

幂等处理。

不承诺：

```text
Exactly Once
```

---

## 49. Delivery Retry

失败重试：

```text
exponential backoff
+
jitter
```

并有：

```text
max attempt
dead letter
manual retry
```

---

## 50. Outbound Signature

未来自定义 Webhook 必须：

```text
对 Payload 签名
```

外部系统可以验证来源。

---

## 51. SSRF 防护

如果未来允许用户配置 Webhook URL：

必须防：

```text
SSRF
```

包括：

```text
localhost
private IP
metadata endpoint
internal service
redirect to private address
DNS rebinding
```

第一版没有公开 Outbound Webhook，但架构必须预留这一安全边界。

---

# Part E: Email Integration

## 52. Email 定位

邮件属于：

```text
External Provider
```

不是 Auth / Notification 模块自己直接调用 SMTP / Provider API。

统一通过：

```text
Email Adapter
```

---

## 53. 第一版邮件用途

至少包括：

```text
Email Verification
Password Reset
New Device Login Security Notice
Email Changed Notice
Provider Bound / Unbound Security Notice
Workspace Invite
```

普通 Comment / Notification：

```text
第一版不发邮件 Digest
```

---

## 54. Transactional Email

第一版邮件属于：

```text
Transactional Email
```

不是：

```text
Marketing Email
```

营销订阅体系不在当前范围。

---

## 55. Email Send Flow

```text
Domain Command
↓
Persist Business State
↓
Outbox Event
↓
Email Queue
↓
Email Worker
↓
Email Adapter
↓
Provider
```

不能在用户 HTTP 请求内：

```text
同步等待邮件 Provider
```

---

## 56. 例外

像：

```text
Request Password Reset
```

用户请求可以在邮件任务可靠入队后：

```text
返回成功
```

不需要等 Provider 真正投递完成。

---

## 57. Email Template

邮件使用：

```text
versioned template
```

业务模块只传：

```text
template type
recipient
template variables
locale
```

不能每个模块手拼 HTML。

---

## 58. Email Security

邮件内容不得包含：

```text
用户密码
长期 Token
内部 Stack Trace
Provider Secret
```

Reset / Verification Link 只携带：

```text
短期一次性 Token
```

---

## 59. Email Link

邮件中的业务链接必须：

```text
固定可信 Origin
```

不能由用户输入直接拼接 Host。

---

## 60. Email Idempotency

例如：

```text
Workspace Invite
Password Reset
Security Notice
```

都需要合理：

```text
dedup
rate limit
```

防止邮件轰炸。

---

## 61. Email Retry

Provider Timeout / 5xx：

```text
Retry
```

明确永久失败：

```text
Invalid Recipient
Hard Bounce
```

不应无限重试。

---

## 62. Bounce / Complaint

如果 Provider 提供：

```text
Bounce
Complaint
Delivery Event
```

可以通过：

```text
Provider Webhook
```

进入系统。

用于：

```text
停止持续发送无效地址
安全诊断
```

---

## 63. Email Provider Failure

邮件 Provider 故障时：

```text
已登录用户编辑
Realtime
Resource
Permission
```

必须继续工作。

受影响：

```text
Verification
Password Reset Delivery
Invite Email
Security Email
```

---

## 64. Email Multi-provider

架构允许：

```text
Primary Email Provider
Secondary Email Provider
```

但第一版不强制双 Provider。

如果未来需要高可用：

```text
Email Adapter
```

可以切换实现。

---

# Part F: External Provider Adapter

## 65. Adapter 原则

所有外部服务统一通过：

```text
Provider Adapter
```

业务模块不得直接依赖厂商 SDK。

---

## 66. Adapter 类型

系统可能存在：

```text
Auth Provider Adapter
Email Provider Adapter
Object Storage Adapter
AI Provider Adapter
Malware Scan Adapter
Media Processing Adapter
Future Webhook Provider Adapter
```

---

## 67. Adapter 标准能力

每个 Adapter 至少明确：

```text
Request
Response Normalize
Timeout
Retry Policy
Error Mapping
Rate Limit Behavior
Circuit Breaker
Observability
Secret Requirements
Idempotency Behavior
```

---

## 68. Provider Raw Response

Provider 原始 Response：

```text
只能停留在 Adapter 边界
```

进入 Domain 前必须 Normalize。

避免业务代码出现：

```text
if provider == wechat
if provider == feishu
```

遍地分支。

---

## 69. Provider Error Normalize

统一分类：

```text
ProviderValidationError
ProviderAuthError
ProviderRateLimited
ProviderTimeout
ProviderUnavailable
ProviderRejected
ProviderProtocolError
```

Domain 不依赖厂商错误码。

---

# Part G: Timeout / Retry / Circuit Breaker

## 70. Timeout

任何外部 Provider 调用：

```text
必须有 Timeout
```

禁止：

```text
无限等待
```

不同 Provider / Operation 可以有不同 Timeout。

---

## 71. Retry

只 Retry：

```text
明确 transient failure
```

例如：

```text
network reset
timeout
selected 5xx
provider rate limit with Retry-After
```

不 Retry：

```text
invalid credential
invalid payload
permission denied
invalid recipient
```

---

## 72. Retry Budget

Retry 必须受：

```text
attempt
time budget
queue budget
```

限制。

不能 Provider 故障时：

```text
无限重试
```

进一步压垮 Provider 和本系统。

---

## 73. Circuit Breaker

Provider 长时间异常：

```text
Circuit Open
```

快速失败或进入队列。

避免每个用户请求都等待相同超时。

---

## 74. Half-open

恢复探测：

```text
Half-open
```

只允许少量测试请求。

Provider 恢复后：

```text
逐渐恢复
```

---

## 75. Bulkhead

不同 Provider 和业务池需要资源隔离。

例如：

```text
Email Worker Pool
AI Worker Pool
Webhook Worker Pool
Asset Processing Pool
```

不能：

```text
Email Provider 卡死
```

耗尽整个 Worker Pool。

---

# Part H: Provider Failure Isolation

## 76. 核心原则

External Provider Failure：

```text
不得扩散成 Core Collaboration Failure
```

---

## 77. 核心链路

核心：

```text
Auth Existing Session
Permission
Resource
Realtime
Persistence
PostgreSQL
```

外围：

```text
Email
AI
Search Provider
Media Processing
Optional External Integration
```

外围故障必须尽量：

```text
Degrade
```

而不是拖垮核心。

---

## 78. 微信故障

微信 Auth Provider 故障：

```text
微信登录暂时不可用
```

但：

```text
邮箱密码登录
飞书登录
已存在 Session
```

继续可用。

---

## 79. 飞书故障

同理：

```text
飞书登录故障
```

不能影响：

```text
邮箱
微信
现有 Session
```

---

## 80. Email 故障

影响：

```text
Verification Email
Password Reset Email
Invite Email
Security Notice
```

不影响：

```text
已有 Session
Resource Editing
Realtime
Comment
```

---

## 81. AI Provider 故障

影响：

```text
AI Task
```

不影响：

```text
Resource Editing
Comment
History
Permission
```

---

## 82. Object Storage 故障

影响：

```text
Asset Upload / Download
Import Binary
Export Binary
```

但纯文本 Resource：

```text
继续工作
```

---

# Part I: Async Integration

## 83. 外部调用默认异步化

非必须即时返回的 Provider 调用：

```text
优先异步
```

例如：

```text
Email
Webhook Delivery
Media Processing
Search Index
```

---

## 84. 用户等待型外部调用

部分操作必须同步知道结果：

```text
OAuth Code Exchange
Sign-in Provider Identity Fetch
Create Signed Upload Session
```

这类调用：

```text
短 Timeout
明确错误
Circuit Breaker
```

不能无限排队。

---

## 85. Async Task 状态

异步 Provider 工作使用：

```text
Task / Delivery State
```

至少：

```text
Queued
Running
Succeeded
Failed
Retrying
DeadLetter
```

具体内部状态可细化。

---

# Part J: Secret Management

## 86. Secret 类型

包括：

```text
WeChat Secret
Feishu Secret
Email API Key
Webhook Signing Secret
Object Storage Credential
AI Provider Key
```

---

## 87. Secret Storage

统一存：

```text
Secret Manager
```

不能：

```text
Git
.env 提交
前端 Bundle
数据库普通配置表明文
日志
```

---

## 88. Secret Rotation

所有长期 Secret 都需要：

```text
rotation strategy
```

系统不能把 Secret 永久写死。

---

## 89. Secret Access

每个 Service 只获取：

```text
自己需要的 Secret
```

例如：

```text
Email Worker
```

不应该拥有：

```text
PostgreSQL Admin
WeChat Secret
AI Provider Key
```

全部权限。

---

# Part K: Webhook / Callback Security

## 90. Public Endpoint

Callback / Webhook 是公网入口。

必须单独保护：

```text
TLS
Rate Limit
Signature / State Verification
Payload Size
Replay Protection
Schema Validation
Observability
```

---

## 91. IP Allowlist

如果 Provider 有稳定官方 IP Range：

```text
可以作为额外防护
```

但：

```text
不能替代 Signature
```

因为 IP 规则可能变化。

---

## 92. Content Type

Webhook / Callback 只接受：

```text
预期 Content-Type
```

未知类型直接拒绝。

---

## 93. Parser Isolation

复杂 XML / JSON / Form Parser：

```text
必须限制大小
深度
字段数量
```

防止 parser abuse。

---

## 94. XXE / XML

如果 Provider 使用 XML：

```text
禁用外部实体
```

防止：

```text
XXE
```

---

## 95. Timestamp

内部所有接收事件记录：

```text
receivedAt
providerTimestamp
```

不能只信任 Provider Timestamp 作为系统因果顺序。

---

# Part L: Outbound HTTP Security

## 96. HTTP Client

系统统一使用：

```text
Hardened Outbound HTTP Client
```

或共享基础库。

负责：

```text
timeout
retry
proxy
TLS
DNS policy
trace
metrics
```

---

## 97. Redirect

Provider 调用默认：

```text
限制 Redirect
```

尤其用户可控 URL。

不能盲目跟随任意：

```text
30x
```

---

## 98. TLS Validation

禁止：

```text
disable TLS verification
```

作为生产修复方式。

---

## 99. Proxy

如果生产环境需要：

```text
egress proxy
```

统一配置。

业务模块不自己处理代理。

---

# Part M: Email / Provider Queue

## 100. Queue Isolation

至少逻辑隔离：

```text
Email Queue
Webhook Queue
AI Queue
Asset Queue
Import / Export Queue
```

避免一种 Provider 故障造成所有异步任务排队。

---

## 101. Queue Backpressure

Provider 降速时：

```text
queue grows
```

必须：

```text
monitor
limit
degrade
```

不能无限占用存储。

---

## 102. Oldest Message Age

不能只监控：

```text
queue length
```

还要监控：

```text
oldest pending age
```

因为低吞吐队列可能长度不大但已经卡很久。

---

# Part N: Dead Letter

## 103. Dead Letter

不可继续自动重试的外部任务进入：

```text
Dead Letter
```

---

## 104. Dead Letter 不是垃圾桶

必须支持：

```text
查看原因
查看 Provider
查看首次 / 最近失败时间
Manual Retry
Discard with Audit
```

---

## 105. 敏感 Payload

Dead Letter 中不得无控制存：

```text
Token
Password
Secret
完整敏感正文
```

需要脱敏或仅存引用。

---

# Part O: Webhook / Email Delivery Identity

## 106. Delivery ID

每次外部发送使用：

```text
deliveryId
```

关联：

```text
eventId
taskId
requestId
traceId
provider
attempt
```

---

## 107. Provider Message ID

如果 Provider 返回：

```text
messageId
requestId
```

保存为诊断字段。

不能作为系统自己的唯一业务 ID。

---

# Part P: Observability

## 108. Gateway Metrics

至少监控：

```text
request rate
latency
error rate
rate limit
payload rejection
auth failure
client version
upstream timeout
```

---

## 109. OAuth Metrics

至少：

```text
wechat auth start
wechat callback success
wechat callback failure
feishu auth start
feishu callback success
feishu callback failure
state validation failure
provider timeout
identity conflict
```

---

## 110. Webhook Metrics

至少：

```text
webhook receive rate
signature failure
replay rejection
duplicate event
processing lag
retry
dead letter
unknown event
```

---

## 111. Email Metrics

至少：

```text
queued
sent
failed
retry
delivery latency
bounce
complaint
provider rate limit
provider unavailable
```

---

## 112. Provider Metrics

统一：

```text
provider latency
success rate
timeout
rate limit
circuit state
retry rate
queue lag
```

Provider 名可以作为低基数 Label。

---

## 113. Trace

同步外部调用：

```text
Client Request
↓
Gateway
↓
Domain
↓
Provider Adapter
↓
External Provider
```

保持：

```text
traceId
```

---

## 114. Async Trace

异步：

```text
Domain Event
↓
Queue
↓
Worker
↓
Provider
```

保留：

```text
eventId
traceId
deliveryId
taskId
```

关联。

---

# Part Q: Logging

## 115. Gateway Log

结构化记录：

```text
requestId
traceId
route
actor
status
duration
errorCode
clientVersion
```

---

## 116. 禁止日志

禁止记录：

```text
password
session credential
oauth code
access token
refresh token
provider secret
reset token
verification token
webhook secret
完整敏感正文
```

---

## 117. Callback Debug

需要 Provider 调试时：

```text
使用脱敏字段
```

而不是：

```text
打印完整 Provider Response
```

---

# Part R: Configuration

## 118. Provider Config

普通 Provider 配置：

```text
enabled
endpoint
timeout
rate limit
feature flag
```

进入：

```text
Config System
```

Secret：

```text
Secret Manager
```

两者分离。

---

## 119. Provider Enable / Disable

每个外部 Provider 必须支持：

```text
Kill Switch
```

例如：

```text
disable wechat login
disable feishu login
disable email sending
disable webhook delivery
```

无需紧急发版。

---

## 120. Feature Flag

新 Provider 可以：

```text
Canary
Workspace Scope
Percentage Rollout
```

逐步启用。

---

# Part S: Provider Versioning

## 121. API Version

Provider API 可能升级。

Adapter 必须明确：

```text
provider api version
schema version
```

不能业务代码散落多个旧版本调用。

---

## 122. Deprecation

Provider 宣布废弃接口时：

```text
Adapter
```

集中升级。

Domain Contract 尽量保持不变。

这正是 Adapter 的价值。

---

# Part T: Testing

## 123. Contract Test

每个 Provider Adapter 至少有：

```text
success response
invalid credential
rate limit
timeout
5xx
malformed response
unknown field
duplicate callback
```

测试。

---

## 124. Webhook Test

至少覆盖：

```text
valid signature
invalid signature
expired timestamp
duplicate event
unknown event
oversized payload
malformed payload
provider retry
```

---

## 125. OAuth Test

至少：

```text
normal callback
state mismatch
expired code
duplicate callback
provider timeout
identity conflict
open redirect attempt
```

---

## 126. Email Test

至少：

```text
queue success
provider timeout
retry
hard bounce
invalid recipient
duplicate send request
template failure
```

---

## 127. Failure Drill

至少验证：

```text
WeChat down
Feishu down
Email provider down
Webhook consumer down
Queue backlog
Secret rotation
Gateway instance failure
```

核心系统必须按预期降级。

---

# Part U: Deployment

## 128. Gateway 多实例

所有 Gateway：

```text
支持水平扩展
```

不能依赖：

```text
单实例内存
```

保存权威 Session / Callback / Webhook State。

---

## 129. Provider Callback 多实例

OAuth `state` /临时 Context：

```text
必须跨实例可验证
```

不能：

```text
发起登录在实例 A
Callback 到实例 B
就失败
```

---

## 130. Webhook Receiver 多实例

Webhook Receiver 可以：

```text
multi instance
```

通过：

```text
Inbox + Unique Constraint
```

或等价方式保证重复事件安全。

---

## 131. Email Worker 多实例

Email Worker：

```text
multiple consumers
```

并使用：

```text
lease / queue ack
idempotent delivery
```

保证 Worker 崩溃后可恢复。

---

# Part V: Data Ownership

## 132. Gateway 不拥有业务数据

Gateway 可以保存：

```text
short-lived technical state
```

但不拥有：

```text
Account
Resource
Permission
Comment
History
```

---

## 133. Adapter 不拥有 Domain State

Provider Adapter：

```text
只负责协议适配
```

不能自己维护：

```text
Account truth
Permission truth
Resource truth
```

---

## 134. Provider Token Ownership

如果 Token 只用于登录：

```text
尽量短期使用
```

如果未来需要长期调用第三方 API：

```text
进入专门 OAuth Credential Storage / Connector Design
```

不能混进普通 Session。

---

# Part W: 与现有模块的关系

## 135. 与 Unified Communication

内部模块继续使用：

```text
Command
Query
Event
Stream
```

Gateway 只是 Client Boundary。

---

## 136. 与 Client Integration

`18-Client-API-Frontend-Integration-Design`

定义：

```text
前端如何调用
```

本设计定义：

```text
这些调用如何进入后端以及如何连接外部世界
```

---

## 137. 与 Auth

`16-Account-Auth-Session-Design`

负责：

```text
Account / Identity / Session
```

本设计负责：

```text
微信 / 飞书协议适配
Callback
Provider Failure
Secret
```

---

## 138. 与 Notification

`17-Comment-Mention-Notification-Design`

负责：

```text
站内通知
```

本设计中的 Email：

```text
是独立外部 Delivery Channel
```

第一版不把普通站内通知全部转成邮件。

---

## 139. 与 Asset

`10-Asset-File-Storage-Design`

负责：

```text
Asset Domain
```

本设计负责：

```text
Object Storage External Adapter
Signed Upload / Download Integration Boundary
```

---

## 140. 与 AI

`12-AI-Task-ChangeSet-Design`

负责：

```text
AI Task / ChangeSet
```

本设计负责：

```text
AI Provider Adapter
Timeout
Retry
Circuit Breaker
Secret
Failure Isolation
```

---

# Part X: 第一版范围

## 141. 第一版必须完成

```text
Client API Gateway
Realtime Gateway
微信 OAuth Callback
飞书 OAuth Callback
Email Adapter
Provider Adapter Framework
Inbound Webhook Framework
Rate Limit
Timeout
Retry
Circuit Breaker
Secret Management
Structured Error Mapping
Observability
Dead Letter / Retry
```

---

## 142. 第一版不开放

```text
Public REST API
Developer Token
User-configurable Webhook
Developer Portal
Webhook Marketplace
OAuth App Platform
Third-party Plugin API
Marketing Email Platform
SMS
Mobile Push
```

---

# Part Y: 核心验收场景

## 143. 场景 1：普通客户端 Query

用户读取 Project Tree。

结果：

```text
Client
↓
Client API Gateway
↓
Session Validate
↓
Project Query
↓
Response
```

Gateway 不包含 Project 业务规则。

---

## 144. 场景 2：微信登录

用户微信授权返回。

结果：

```text
Callback Gateway
↓
Validate State
↓
Exchange Code
↓
Normalize Provider Identity
↓
Account Service
↓
Create / Replace Session
```

微信字段不泄漏进其他业务模块。

---

## 145. 场景 3：飞书重复 Callback

同一个 Callback 被重放。

结果：

```text
不会创建第二个 Account
不会创建错误双 Session
```

---

## 146. 场景 4：微信 Provider Down

微信 API Timeout。

结果：

- 微信登录返回明确 ProviderUnavailable
- Circuit Breaker 逐步打开
- 邮箱 / 飞书 / Existing Session 正常

---

## 147. 场景 5：Email Provider Down

用户发起 Password Reset。

结果：

- Reset Request 可靠记录
- Email Task 入队
- Provider 失败进入 Retry
- 已登录协作功能完全不受影响

---

## 148. 场景 6：Webhook 重复投递

Provider 连续投递同一 eventId 3 次。

结果：

```text
Receiver 可以接收 3 次
业务效果只发生一次
```

---

## 149. 场景 7：伪造 Webhook

攻击者发送 Payload，无合法签名。

结果：

```text
Reject
No Business Effect
Security Metric++
```

---

## 150. 场景 8：旧 Webhook 重放

攻击者截获一小时前合法请求并重放。

结果：

```text
Timestamp / Event Dedup
↓
Reject or No-op
```

---

## 151. 场景 9：Webhook Worker 崩溃

Receiver 已可靠接收。

Worker 处理中崩溃。

结果：

```text
Event 重新领取
幂等处理
最终完成
```

---

## 152. 场景 10：Provider 大面积 5xx

系统：

```text
Retry Budget
Circuit Breaker
Queue Backpressure
Alert
```

共同作用。

不会无限线程等待。

---

## 153. 场景 11：邮件轰炸

攻击者不断点击：

```text
Forgot Password
```

结果：

```text
Account / IP / Operation Rate Limit
+
Email Dedup
```

限制发送。

---

## 154. 场景 12：Open Redirect

攻击者构造 OAuth：

```text
returnTo=https://evil.example
```

结果：

```text
Reject / Normalize to Safe Internal Route
```

---

## 155. 场景 13：Secret Rotation

飞书 Secret 更新。

结果：

- 新 Secret 生效
- 无需修改业务代码
- 不暴露 Secret
- Rotation 可审计

---

## 156. 场景 14：Gateway Instance Down

多个 Gateway 实例。

一个崩溃。

结果：

```text
Load Balancer 移除
其他实例继续服务
```

---

## 157. 场景 15：Callback 落到不同实例

登录发起在 Gateway A。

Provider Callback 到 Gateway B。

结果：

```text
state 仍可验证
```

不依赖 A 内存。

---

## 158. 场景 16：Email Hard Bounce

Provider 返回：

```text
hard bounce
```

结果：

- 标记该 Delivery 不再自动 Retry
- 记录诊断
- 后续发送策略可以降级
- 不影响 Account 本身

---

## 159. 场景 17：Unknown Provider Event

Webhook 收到未来新事件类型。

结果：

```text
安全记录 / 忽略
```

系统不崩溃。

---

## 160. 场景 18：Large Asset Upload

用户上传大文件。

结果：

```text
Gateway 只创建 Upload Session
Binary 直接进入 Object Storage
```

Gateway 不成为大文件数据通道。

---

# Part Z: 本地 AI 实现自由度

## 161. 本地 AI 可以自行选择

基础技术产品不再由本地 AI 自由选择，统一遵守 `26-Technology-Stack-Decision.md`：

```text
Edge = 随部署方案决策（由 docker skills 决定，ADR 0056；必须支持 HTTPS / WSS）
Queue / Event Bus = NATS JetStream
Python HTTP Client = httpx
Cache = Valkey
Observability = OpenTelemetry stack
```

仍可由部署环境 / Provider Adapter 选择的只有厂商或库级实现，例如：

```text
具体 WAF Provider
云 Secret Manager / Key Vault Provider
Email Provider
Circuit Breaker Library
OAuth Library
XML / JSON Parser
```

这些选择不得改变本设计的边界、安全、失败隔离、可恢复和可观测性要求。

---

# Part AA: 架构硬约束

## 162. 架构硬约束

1. Gateway 只做入口治理，不承载 Domain Logic。
2. Client API、Realtime、Provider Callback、Webhook 必须有明确逻辑边界。
3. 第一版不开放 Public API 和用户自定义 Webhook。
4. 微信和飞书必须通过 Auth Provider Adapter 接入。
5. Provider 原始协议不得泄漏到 Account / Resource 等 Domain。
6. OAuth Callback 必须验证 state，并防 Open Redirect。
7. Provider Secret 只能进入 Secret Manager。
8. Provider Callback 必须幂等。
9. Provider Identity 必须通过 PostgreSQL 唯一约束防重复绑定。
10. Webhook 必须验签、限流、防重放、幂等。
11. Webhook 应快速 ACK，复杂业务异步处理。
12. Webhook 原始签名如果依赖 Raw Body，必须在解析前验证所需原始数据。
13. Email 必须通过 Email Adapter 和异步 Queue 发送。
14. 邮件 Provider 故障不能影响核心协作。
15. 外部 Provider 调用必须有 Timeout。
16. Retry 只用于可恢复错误，并有 Retry Budget。
17. 外部 Provider 必须支持 Circuit Breaker 或等价故障隔离。
18. 不同外部工作负载必须 Bulkhead 隔离。
19. Dead Letter 必须可诊断、可重试，不是黑洞。
20. 大文件不得通过普通 API Gateway 转发。
21. 外部 Provider Raw Error 必须 Normalize。
22. Gateway / Callback / Webhook 必须支持多实例。
23. Callback State / Webhook Dedup 不得依赖单实例内存。
24. Secret 必须支持 Rotation。
25. 外部调用必须统一 Trace / Metrics / Structured Log。
26. 敏感 Token / Secret / Password 不得进入日志。
27. 任何外围 Provider 故障不得默认升级为 Resource / Realtime / Persistence 故障。
28. 本设计与 04、05、16、18、19 号设计保持一致。

---

## 163. 最终模型

```text
                         Internet
                            │
                            ▼
                      Edge Gateway
                            │
          ┌─────────────────┼──────────────────┐
          ▼                 ▼                  ▼
    Client API         Realtime          Callback / Webhook
      Gateway           Gateway               Gateway
          │                 │                  │
          ▼                 ▼                  ▼
      Domain API      Resource Stream     Integration Layer
                                                │
                               ┌────────────────┼────────────────┐
                               ▼                ▼                ▼
                         Auth Provider       Email           Webhook
                           Adapter           Adapter          Adapter
                               │                │                │
                               ▼                ▼                ▼
                         WeChat / Feishu   Email Provider   External System
```

故障隔离：

```text
External Provider Failure
↓
Timeout
↓
Retry Budget
↓
Circuit Breaker
↓
Queue / Degrade
↓
Alert

Core Collaboration
继续运行
```

最终边界：

> Gateway 负责把外部世界安全地接入系统，Provider Adapter 负责把不同厂商协议收口成统一语义，业务模块只处理自己的 Domain；任何微信、飞书、邮件、Webhook 或其他外部 Provider 故障，都不能穿透这层边界拖垮 Resource、Realtime、Permission 和 Persistence 主链。
