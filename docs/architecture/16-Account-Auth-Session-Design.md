# Account, Auth & Session Design

## 1. 目标

本设计定义系统中的账号、注册、登录、第三方登录、Session、最多 2 个活跃设备 Session、账号恢复、匿名只读 Share Link 与安全边界。

本模块解决：

> 用户是谁、如何建立可信身份、如何登录、如何失效旧登录、如何通过微信 / 飞书登录、如何恢复账号，以及系统如何让 Permission、Realtime、AI、Plugin、Share 等模块统一识别当前 Actor。

本设计按可上线产品标准设计。

本项目第一版产品决策已经确定：

```text
注册方式
= 自由注册

基础登录
= 邮箱 + 密码，独立完成注册与登录

第三方登录
= 微信 / 飞书可选，不是注册或登录的前置条件

设备策略
= 最多 2 个活跃设备 Session

双设备上限规则
= 新设备登录成功后，自动使旧设备 Session 失效并下线

MFA
= 不做，后续也不规划

Share Link
= 匿名只读
= 编辑 / 评论必须登录
```

---

## 2. 核心对象

系统统一使用以下身份概念：

```text
Account
Identity
Session
Device
Auth Provider
Anonymous Share Viewer
```

职责：

```text
Account
= 系统中的长期用户账号

Identity
= 用户用于证明“我是这个 Account”的登录身份

Session
= 一次已经认证成功的登录会话

Device
= 当前 Session 所属客户端设备上下文

Auth Provider
= Email / WeChat / Feishu 等身份来源

Anonymous Share Viewer
= 通过 Share Link 只读访问、但没有登录账号的临时访问主体
```

---

## 3. Account

每个用户拥有稳定：

```text
userId
```

`userId` 是系统内部长期身份。

以下信息都不能替代 `userId`：

```text
email
微信 openid / unionid
飞书 open_id / union_id / user_id
display name
session id
```

用户更换邮箱、绑定或解绑第三方账号时：

```text
userId
```

保持不变。

---

## 4. Identity

一个 Account 可以绑定多个 Identity。

第一版支持：

```text
Email Password Identity
WeChat Identity
Feishu Identity
```

例如：

```text
Account user_123

├── email: user@example.com
├── wechat: provider identity
└── feishu: provider identity
```

这些身份最终都映射到同一个：

```text
userId
```

---

## 5. 登录入口

第一版登录页提供：

```text
邮箱 + 密码
```

邮箱账号可以独立注册和登录，不要求绑定或使用微信、飞书。若产品启用第三方登录，微信与飞书只是可选入口。

不显示：

```text
GitHub
Google
Microsoft
Apple
QQ
```

后续如果产品需要，可以通过 Auth Provider Adapter 扩展。

---

## 6. 注册

第一版采用：

```text
自由注册
```

用户可以使用：

```text
邮箱 + 密码
```

创建账号。

注册后：

```text
邮箱自动验证，直接进入 Active
```

系统自动建立登录 Session 并授予正常产品权限；注册流程不发送验证邮件，也不依赖邮件投递。

---

## 7. Email Verification

普通邮箱注册会自动完成验证并立即进入 `Active`，不经过邮箱未验证的受限模式。`VerifyEmail` 与 `ResendEmailVerification` 仅作为兼容入口保留，不是新注册或登录的前置步骤。`PendingVerification` 不由正常注册流程产生。

---

## 8. 密码要求

系统需要合理的密码策略。

不建议使用：

```text
必须包含大写 + 小写 + 数字 + 特殊字符
```

这种僵硬复杂度规则。

更建议：

```text
最低长度
弱密码检测
常见泄漏密码拒绝
支持 Password Manager
```

具体长度由实现根据安全策略确定。

---

## 9. 密码存储

密码必须使用成熟密码 Hash。

例如：

```text
Argon2id
```

或同等级成熟方案。

禁止：

```text
明文密码
可逆加密保存密码
MD5
SHA1
单纯 SHA256
```

数据库泄漏后也不能直接得到用户密码。

---

## 10. 密码找回

第一版必须支持：

```text
Forgot Password
```

流程：

```text
用户输入邮箱
↓
发送短期 Password Reset Link
↓
用户设置新密码
↓
旧密码失效
↓
旧 Session 按安全策略失效
```

---

## 11. Password Reset Token

Reset Token 必须：

```text
随机
短期有效
单次使用
可撤销
服务端安全存储
```

不能：

```text
明文长期存数据库
```

Token 使用成功后立即失效。

---

## 12. 防邮箱枚举

以下入口：

```text
登录
注册
忘记密码
```

不应通过明显不同响应泄露：

```text
这个邮箱是否存在
```

产品提示需要在用户体验与安全之间平衡。

---

## 13. 微信登录（可选）

如产品启用微信登录：

```text
微信第三方登录（可选）
```

微信 Auth Provider 负责：

```text
OAuth / Authorization
Provider Identity
Account Binding
Login
```

业务模块只识别：

```text
userId
```

不直接依赖微信身份字段。

---

## 14. 飞书登录（可选）

如产品启用飞书登录：

```text
飞书第三方登录（可选）
```

飞书 Auth Provider 负责：

```text
OAuth / SSO Authorization
Provider Identity
Account Binding
Login
```

业务模块不直接依赖：

```text
open_id
union_id
tenant key
```

作为系统 Account Identity。

---

## 15. Auth Provider Adapter

微信与飞书统一通过：

```text
Auth Provider Adapter
```

接入。

Adapter 至少负责：

```text
Build Authorization Request
Handle Callback
Validate State
Exchange Code
Fetch Provider Identity
Normalize Provider Account
```

Account Service 只接收标准化结果。

---

## 16. Provider Identity 唯一性

第三方登录必须保存稳定 Provider Identity。

例如：

```text
provider
providerSubject
```

形成唯一绑定。

不能仅通过：

```text
昵称
头像
手机号展示值
邮箱展示值
```

判断是不是同一个第三方用户。

---

## 17. 第三方首次登录

用户第一次微信 / 飞书登录时：

如果没有现有绑定：

```text
Provider Identity
↓
创建新 Account
或
进入账号合并 / 绑定流程
```

产品需要避免悄悄创建重复账号。

---

## 18. Account Linking

同一个人可能：

```text
先用邮箱注册
↓
以后用微信登录
```

系统应支持：

```text
绑定微信
绑定飞书
```

到已有 Account。

绑定过程必须先确认：

```text
当前 Account 已登录
+
第三方授权成功
```

不能仅凭相同昵称自动合并。

---

## 19. Email 与 Provider 自动合并

如果第三方 Provider 返回相同邮箱：

```text
默认不能只因为邮箱相同就静默合并 Account
```

除非：

```text
Provider 对该邮箱有可信 verified 标记
+
产品明确接受自动合并
```

第一版建议：

```text
进入显式绑定 / 确认流程
```

更安全。

---

## 20. Unlink Provider

用户可以解绑：

```text
微信
飞书
```

但解绑后 Account 必须仍然至少保留一种有效登录方式。

例如：

```text
邮箱密码
或
另一个 Provider
```

不能把账号解绑成：

```text
没有任何登录方式
```

---

## 21. Session

登录成功后创建：

```text
Session
```

Session 是服务端可失效的认证状态。

第一版采用：

```text
server-recognized session
```

而不是完全不可撤销的长期自包含身份。

---

## 22. Session Identity

Session 至少关联：

```text
sessionId
userId
device context
createdAt
lastSeenAt
expiresAt
status
```

具体字段由本地 AI 根据实现确定。

---

## 23. 最多 2 个活跃设备 Session

第一版明确：

> 一个 Account 同一时间最多允许 2 个有效 Device Sessions。

同一浏览器内多个 Tab：

```text
共享一个 Device Session
不额外占用设备名额
```

邮箱、微信、飞书登录最终都遵守同一 Session 上限。

---

## 24. 新设备登录

当当前 Active Device Session 少于 2 个：

```text
Create New Session
↓
Keep Existing Valid Session
```

当第 3 个设备登录成功：

```text
Create New Session
↓
Select Oldest Active Device Session
↓
Oldest Session → Replaced
↓
Notify Replaced Device
```

新设备登录不因已有设备在线而被拒绝。

---

## 25. 被替换设备自动下线

被替换 Session 必须及时失去：

```text
HTTP API
Realtime WebSocket
Resource Subscription
AI Task Write Control
Account Settings
```

另一个仍在 2-device limit 内的合法 Session 不受影响。

---

## 26. Realtime Session Replacement

被替换设备如果存在 WebSocket，系统应发送 `SessionReplaced` 或等价控制消息，然后关闭其认证 Subscription。

客户端反馈必须明确这是“设备名额被新登录替换”，不是普通网络错误。

---

## 27. 本地未同步内容

任何被替换设备都不能静默删除本地未同步 Yjs 内容。

重新登录后重新检查 Permission / Lifecycle；仍有写权限时可以 CRDT Sync，无写权限时允许复制 / 导出恢复。

---

## 28. Session 失效传播

Session Replacement 必须快速传播到 API、Realtime、Permission Context、AI Control 和其他认证入口。

不能只在 Auth Service 单实例内存里修改。

---

## 29. Session Version / Epoch

生产实现建议为 Account 维护：

```text
sessionVersion / authEpoch
```

或等价机制。

当：

```text
新设备登录
密码重置
账号禁用
强制登出
```

发生时：

```text
旧 Session
```

可以统一失效。

具体字段名由本地 AI 决定。

---

## 30. Session Cookie / Token

浏览器登录推荐使用：

```text
Secure
HttpOnly
SameSite
```

Cookie 或等价安全 Session Credential。

不建议把长期认证凭证长期存：

```text
localStorage
```

具体 Session Token 格式由实现决定。

---

## 31. CSRF

如果使用 Cookie Session：

```text
必须处理 CSRF
```

可以使用：

```text
SameSite
CSRF Token
Origin / Referer Validation
```

等成熟方案组合。

---

## 32. XSS

Auth 设计不能把安全建立在：

```text
“前端永远没有 XSS”
```

因此：

```text
HttpOnly Cookie
Content Security Policy
Output Escaping
Sanitization
```

等措施需要协同。

详细前端安全以后可进入 Security Hardening Design。

---

## 33. Session Expiry

Session 必须：

```text
有过期时间
```

可以同时支持：

```text
Idle Expiry
Absolute Expiry
```

具体时长由产品体验决定。

不能：

```text
永久有效
```

---

## 34. Session Refresh

可以使用：

```text
Session Rotation
```

或：

```text
Refresh Credential
```

延长已登录状态。

无论采用哪种实现：

```text
旧 Credential
```

必须可撤销。

---

## 35. Session Rotation

关键安全事件后应 Rotate Session。

例如：

```text
登录成功
密码修改
邮箱修改
Provider Binding
高风险账号设置变化
```

防止 Session Fixation。

---

## 36. 修改密码

用户修改密码时：

```text
需要验证当前身份
```

成功后建议：

```text
Rotate Current Session
```

由于系统最多允许 2 个活跃设备 Session：

```text
旧 Session
```

自然全部失效。

---

## 37. Password Reset 后

通过邮箱 Reset Password：

```text
所有旧 Session
```

必须失效。

完成 Reset 后：

```text
可以要求重新登录
```

或安全地创建一个新的唯一 Session。

---

## 38. 邮箱修改

修改邮箱需要：

```text
当前登录身份验证
+
新邮箱验证
```

必要时对旧邮箱发送：

```text
安全通知
```

避免账号被静默接管。

---

## 39. Account Disable

系统必须支持：

```text
Account Disabled
```

例如：

- 安全风险
- 管理封禁
- 用户主动停用
- 法律 / 合规

禁用后：

```text
所有 Session
```

立即失效。

---

## 40. Account Delete

用户可以发起：

```text
Delete Account
```

这不是立即物理删除所有数据。

应进入：

```text
Delete Request
↓
Grace Period
↓
Final Deletion
```

第一版 Account Delete Grace Period 为：

```text
30 days
```

在 Final Deletion 前用户可以取消删除请求并恢复账号。30 天属于产品 Policy，应保持可配置，但第一版默认与正式产品行为固定为 30 天。

---

## 41. Account Delete 与 Workspace

删除个人 Account 前必须处理：

```text
Owned Workspace
```

例如：

- 转移 Owner
- 删除 Workspace
- 取消删除账号

不能出现：

```text
唯一 Workspace Owner 被删除
```

导致资源无人管理。

---

## 42. Account Delete 与内容

用户创建的 Resource 不应因为 Account 删除自动全部物理销毁。

资源归属：

```text
Workspace / Project
```

而不是永久绑定个人 Account。

用户删除账号后：

```text
Resource
History
Audit
```

按 Workspace 生命周期继续保留。

---

## 43. Deleted User Display

历史中引用已删除用户时：

可以显示：

```text
Deleted User
```

或保留必要显示名快照。

不能因为用户删除账号：

```text
History / Audit 外键全部断裂
```

---

## 44. Anonymous Share Viewer

Share Link 允许：

```text
匿名只读
```

Anonymous Viewer：

```text
不是 Account
不是 User
不是 Member
```

它是一种受 Share Link 限制的临时 Actor。

---

## 45. 匿名 Share 权限

Anonymous Viewer 只能：

```text
Read
```

不能：

```text
Edit
Comment
Manage
Invite
AI Write
Plugin Write
History Restore
Download Sensitive Asset（除非 Share Policy 明确允许）
```

---

## 46. 匿名编辑

第一版明确不支持：

```text
Anonymous Edit
```

---

## 47. 匿名评论

第一版明确不支持：

```text
Anonymous Comment
```

评论必须登录。

---

## 48. 从匿名只读进入编辑

匿名用户打开 Share Link 后点击：

```text
Edit
Comment
```

产品进入：

```text
Login / Register
```

完成认证后：

```text
重新计算正式 Account Permission
```

不能把匿名 Share Credential 直接升级成 Edit 身份。

---

## 49. Share Link 与 Session 分离

Share Link：

```text
不是 Session
```

登录 Session：

```text
不是 Share Link
```

Anonymous Viewer 的访问能力来自：

```text
Share Token
```

登录用户能力来自：

```text
Account + Permission
```

两条链路必须分开。

---

## 50. Logged-in User + Share Link

已登录用户打开 Share Link 时：

系统可以综合：

```text
Account Permission
+
Share Link Permission
```

得到最终可用能力。

但不能让 Share Link 降低原有正式权限。

例如：

```text
用户本来 = Edit
打开 Read Share Link
```

仍然可以按正式 Edit 权限使用。

---

## 51. Share Link Revoke

Share Link 被撤销：

```text
Anonymous Viewer
```

必须失去访问。

如果匿名 Viewer 正在打开 Resource：

```text
相关匿名 Subscription
```

应被关闭。

---

## 52. 匿名 Realtime

匿名只读用户如果产品需要看到实时内容：

```text
可以加入 Read-only Realtime Subscription
```

但：

```text
不能发送正文 Update
不能发送需要登录身份的评论
```

第一版 Anonymous Viewer 不参与 Presence。

```text
no anonymous cursor
no anonymous presence member
no anonymous online count
```

Awareness 不为匿名 Viewer 建立可被正式协作者识别的 Presence Actor。

---

## 53. Anonymous Viewer Privacy

系统不需要为匿名 Viewer 建立长期用户档案。

可以记录：

```text
share access audit
basic security context
```

但应最小化：

```text
持久身份追踪
```

---

## 54. Email Login Rate Limit

登录必须有：

```text
Rate Limit
```

至少按：

```text
IP
Account / Email
Device / Client Context
```

进行受控限制。

避免暴力破解。

---

## 55. Provider Login Rate Limit

微信 / 飞书 Callback 也需要：

```text
Rate Limit
State Validation
Replay Protection
```

不能因为第三方登录就跳过安全控制。

---

## 56. Login Abuse Protection

系统应支持：

```text
progressive delay
temporary lock
risk signal
security alert
```

或等价机制。

不能把“账号锁死 24 小时”作为唯一防暴力破解策略。

---

## 57. Captcha

Captcha 可以作为：

```text
Risk-based Tool
```

在异常登录 / 注册流量下启用。

不要求所有用户每次登录都做 Captcha。

---

## 58. Session Theft Detection

系统可以记录：

```text
device fingerprint summary
IP region summary
user agent summary
```

用于识别：

```text
明显异常 Session 使用
```

但不能把脆弱 Fingerprint 当作唯一身份。

---

## 59. 设备 Session 上限与网络变化

用户：

```text
Wi-Fi
→ 4G
→ VPN
```

不应因此被当成新设备自动踢下线。

设备判断以：

```text
Session
```

为主，不依赖单一 IP。

---

## 60. Device

第一版 Device 主要用于：

```text
显示当前登录环境
安全通知
Session 诊断
```

由于系统采用最多 2 个活跃设备 Session：

```text
不需要复杂的“设备列表管理多个活跃 Session”
```

但可以保留：

```text
Current Device
Recent Login
```

信息。

---

## 61. 登录记录

Account Settings 可以显示：

```text
最近登录时间
登录方式
大致设备信息
大致地区 / IP 信息（按隐私策略）
```

用于用户发现异常登录。

不需要展示过度精确位置。

---

## 62. 新设备通知

新设备登录并踢掉旧设备时：

建议发送：

```text
安全通知
```

例如：

```text
邮箱通知
```

内容包括：

```text
时间
大致设备
如果不是本人应怎么处理
```

---

## 63. 微信 / 飞书绑定通知

绑定或解绑：

```text
微信
飞书
```

建议发送安全通知。

避免攻击者静默添加新的登录方式。

---

## 64. Auth Error Model

至少区分：

```text
Invalid Credential
Email Not Verified
Session Expired
Session Replaced
Account Disabled
Provider Error
Provider Identity Conflict
Reset Token Expired
Rate Limited
Share Link Invalid
Share Link Expired
Share Link Revoked
```

客户端根据：

```text
errorCode
```

展示正确 UI。

---

## 65. Session Replaced

旧设备收到：

```text
SessionReplaced
```

时，需要明确告诉用户：

> 当前账号已在另一台设备登录。

不能只显示：

```text
401 Unauthorized
```

让用户误以为系统坏了。

---

## 66. Auth 与 Permission 边界

Auth 回答：

```text
“你是谁”
```

Permission 回答：

```text
“你能做什么”
```

两者必须分离。

登录成功：

```text
不代表可以访问所有 Resource
```

第三方 Provider：

```text
不决定 Resource Permission
```

---

## 67. Auth 与 Realtime

建立 WebSocket 前：

```text
验证当前 Session
```

连接期间：

```text
Session 可能被新设备替换
```

Realtime 必须消费：

```text
SessionInvalidated / SessionReplaced
```

并及时关闭旧认证上下文。

---

## 68. Auth 与 AI

AI Task 创建时记录：

```text
initiating userId
```

如果 Session 被替换：

```text
已运行 Task
```

不必仅因为浏览器 Session 变化自动取消。

但最终高风险写入仍然根据：

```text
Account status
Permission
Task authorization
```

重新检查。

---

## 69. Session 被替换与 AI Task

旧设备发起 AI Task：

```text
Task Running
↓
新设备登录
↓
旧 Session 失效
```

Task 可以继续运行。

但：

```text
旧设备不能继续发新的控制命令
```

新设备如果同一 Account 登录：

```text
可以恢复查看 Task
```

---

## 70. Auth 与 Plugin

Plugin 代表用户调用系统时：

```text
不能只信任前端 userId
```

必须绑定：

```text
可信 Account Identity
+
Plugin Scope
+
Permission
```

---

## 71. Auth 与 Audit

至少审计：

```text
Account Created
Password Reset
Email Changed
WeChat Bound
WeChat Unbound
Feishu Bound
Feishu Unbound
Session Replaced
Account Disabled
Account Delete Requested
Sensitive Login Anomaly
```

普通每次成功请求不进入 Audit。

---

## 72. Auth 与 Operations

运维人员：

```text
不能通过修改数据库字段
```

伪装成某个用户正常登录。

如果需要：

```text
Support Impersonation
```

以后必须单独设计：

```text
强审计
明确 UI
临时权限
```

第一版不做。

---

## 73. Provider Failure

微信或飞书登录暂时故障时：

```text
邮箱 + 密码登录
```

仍然可用。

第三方 Provider 是：

```text
可降级 Auth Path
```

不能成为账号系统唯一入口。

---

## 74. Email Service Failure

邮件服务故障会影响：

```text
邮箱验证
密码找回
安全通知
```

但已存在 Session：

```text
不应自动失效
```

登录是否继续允许取决于账号当前状态。

---

## 75. Single Device Race

两个设备几乎同时登录：

```text
Device A
Device B
```

系统必须最终只有：

```text
一个 Active Session
```

不能出现：

```text
A 和 B 都认为自己是当前唯一设备
```

具体事务 / version / lock 由本地 AI 选择。

---

## 76. 登录幂等

Provider Callback / Login Complete 可能因为网络重试重复提交。

必须避免：

```text
重复创建 Account
重复绑定 Provider
重复创建多个 Active Session
```

---

## 77. Account Creation Race

两个登录请求同时尝试：

```text
创建同一邮箱 Account
```

必须通过：

```text
PostgreSQL Unique Constraint
+
Transaction
```

保证最终唯一。

---

## 78. Provider Binding Race

同一个微信 / 飞书 Provider Identity：

```text
不能同时绑定两个 Account
```

必须使用数据库唯一约束保证。

---

## 79. PostgreSQL 权威状态

以下 Account / Auth 状态使用 PostgreSQL 作为权威存储：

```text
Account
Email Identity
Provider Identity
Session
Session Invalidation State
Password Reset
Email Verification
Account Lifecycle
Security Audit Metadata
```

---

## 80. Cache

可以缓存：

```text
Session Validation
Account Basic State
Provider Config
```

但：

```text
Account Disabled
Session Replaced
Password Reset
```

必须能够快速失效旧缓存。

---

## 81. Session Validation 性能

Session Check 是高频路径。

不能每个请求都执行：

```text
昂贵多表 Join
```

可以使用：

```text
短期 Cache
Session Version
轻量 Session Record
```

优化。

但缓存不能造成：

```text
旧设备被踢后仍能长期访问
```

---

## 82. Session Invalidation Event

至少产生：

```text
SessionCreated
SessionReplaced
SessionInvalidated
AccountDisabled
AccountDeleted
```

供：

```text
Realtime
Permission Cache
AI Control
Plugin
```

消费。

---

## 83. Account Event

典型 Event：

```text
AccountCreated
EmailVerified
EmailChanged
PasswordChanged
PasswordReset
WeChatLinked
WeChatUnlinked
FeishuLinked
FeishuUnlinked
AccountDeletionRequested
AccountDeleted
```

遵守 Unified Module Communication Design。

---

## 84. Auth Command

Canonical Command 名称：

```text
RegisterWithEmail
VerifyEmail
ResendEmailVerification
LoginWithPassword
Logout
Reauthenticate
RequestPasswordReset
ResetPassword
RequestAccountDeletion
CancelAccountDeletion
StartWeChatLogin
CompleteWeChatLogin
StartFeishuLogin
CompleteFeishuLogin
LinkWeChat
UnlinkWeChat
LinkFeishu
UnlinkFeishu
ChangePassword
ChangeEmail
```

这些名称是该 Domain 的正式 Command 名，与 `/contracts/registry.yaml` 中注册的 `logicalName` 一一对应；HTTP Route 与 URL 可以演进，Canonical Command 名不得漂移。

`VerifyEmail` 对应 §7 Email Verification；`ResendEmailVerification` 对应 §117 Email Token Lifecycle；`Reauthenticate` 对应 §104–§105 Recent Auth；`CancelAccountDeletion` 对应 §40 Account Delete 的宽限期取消路径。

---

## 85. Auth Query

典型 Query：

```text
GetCurrentAccount
GetCurrentSession
GetLoginSecurityInfo
GetBoundProviders
GetAccountStatus
```

---

## 86. Logout

用户主动 Logout：

```text
当前唯一 Session
```

立即失效。

Logout 后：

```text
Realtime
```

及时断开认证 Subscription。

---

## 87. Logout All

因为第一版有明确的设备 Session 上限：

```text
Logout
```

实际上就是：

```text
Logout All Active Sessions
```

未来若改变多设备策略，再扩展。

---

## 88. Session Resume

页面刷新或浏览器重启：

```text
如果 Session 仍有效
```

自动恢复登录。

不能每次刷新都要求重新输入密码。

---

## 89. Remember Me

第一版可以不单独提供：

```text
Remember Me
```

而由统一 Session Expiry 管理。

这样产品更简单。

以后如有需求再增加：

```text
short session / long session
```

策略。

---

## 90. Provider Logout

用户从系统 Logout：

```text
只需要让本系统 Session 失效
```

一般不需要：

```text
强制退出微信 / 飞书账号本身
```

避免影响用户其他应用。

---

## 91. Provider Token

如果微信 / 飞书 Token 仅用于：

```text
完成登录
```

则使用后应尽量减少长期保存。

如果未来需要调用 Provider API：

```text
另行设计 Connector / OAuth Token Storage
```

不要混入普通 Auth Session。

---

## 92. Auth Provider Secret

微信 / 飞书：

```text
client secret
app secret
```

必须进入：

```text
Secret Manager
```

不能：

```text
提交 Git
写入前端
写普通日志
```

---

## 93. OAuth State

微信 / 飞书授权流程必须使用：

```text
state
```

防止：

```text
CSRF
login confusion
```

必要时配合：

```text
PKCE
nonce
```

具体按 Provider 能力实现。

---

## 94. Redirect URI

OAuth Redirect URI：

```text
必须严格 allowlist
```

不能允许用户提交任意 redirect URL。

防止 Token / Authorization Code 被窃取。

---

## 95. Open Redirect

登录完成后的：

```text
returnTo
```

必须验证。

不能：

```text
/login?next=https://evil.example
```

形成 Open Redirect。

---

## 96. Session Fixation

登录成功后：

```text
必须创建 / Rotate 新 Session
```

不能沿用登录前可被攻击者预先控制的 Session Identity。

---

## 97. Cookie Scope

Auth Cookie：

```text
Domain
Path
Secure
SameSite
```

必须最小化。

不应无必要共享给：

```text
无关子域
静态 CDN
第三方页面
```

---

## 98. CORS

如果前后端跨 Origin：

```text
CORS
```

必须使用明确 allowlist。

不能：

```text
Access-Control-Allow-Origin: *
+
Credentials
```

这种危险组合。

---

## 99. 登录页安全

登录页不应加载：

```text
不可信第三方脚本
```

避免认证 Credential 被页面脚本窃取。

必要第三方 SDK 需要：

```text
来源限制
版本控制
CSP
```

---

## 100. Account Enumeration

第三方绑定错误、密码 Reset、登录失败等场景：

```text
不能把 Account 是否存在
```

过度暴露给未认证攻击者。

内部日志可以记录真实错误原因。

---

## 101. Brute Force

密码登录失败：

```text
不能无限快速尝试
```

系统至少具备：

```text
Rate Limit
Progressive Delay
Abuse Detection
```

---

## 102. Credential Stuffing

系统应对：

```text
大量已泄漏邮箱密码组合尝试
```

具备基础防护。

可以通过：

```text
IP / Account Rate
Suspicious Pattern
Captcha
Temporary Protection
```

处理。

---

## 103. No MFA

项目明确：

```text
不做 MFA
后续也不规划 MFA
```

因此安全设计不能把：

```text
“未来加 MFA”
```

当作弥补当前账号安全缺口的借口。

必须把基础能力做好：

```text
强密码 Hash
泄漏密码防护
登录限流
Device Session
Session Rotation
邮箱安全通知
Provider 安全绑定
异常登录检测
快速 Session 失效
```

---

## 104. 高风险账号操作

虽然不做 MFA，但以下操作仍应要求：

```text
recent authentication
```

或重新验证密码 / Provider。

例如：

```text
修改密码
修改邮箱
绑定 / 解绑登录 Provider
删除账号
```

不能只因为浏览器里有一个 오래된 Session 就直接执行。

---

## 105. Recent Auth

Session 中可以记录：

```text
lastStrongAuthAt
```

或等价语义。

高风险操作超过时间窗口时：

```text
要求重新输入密码
或
重新完成微信 / 飞书认证
```

这不是 MFA。

它是：

```text
Re-authentication
```

---

## 106. Account Recovery

账号恢复主路径：

```text
Verified Email
```

因此：

```text
邮箱验证
```

是第一版 Account Security 的核心。

如果用户只有微信 / 飞书登录且没有验证邮箱：

```text
应提示补充 Recovery Email
```

避免 Provider 账号异常后完全无法恢复。

---

## 107. Recovery Email

建议所有 Account 最终都拥有：

```text
verified recovery email
```

即使最初通过：

```text
微信
飞书
```

注册。

产品可以在首次登录后引导补充。

---

## 108. Provider-only Account

如果第一版允许：

```text
只通过微信 / 飞书创建 Account
```

则需要明确：

```text
未绑定邮箱时
只能通过当前 Provider 恢复登录
```

系统应提示绑定邮箱。

---

## 109. Display Name / Avatar

微信 / 飞书首次登录可以导入：

```text
display name
avatar
```

作为初始资料。

但用户资料以后由本系统 Account Profile 管理。

Provider 后续变化：

```text
不应自动无条件覆盖用户已经修改的资料
```

---

## 110. Profile 与 Auth 分离

```text
display name
avatar
bio
```

属于：

```text
Profile
```

不是 Auth Credential。

Account Profile 以后可以独立设计。

---

## 111. Auth 与 Workspace Invite

用户收到 Workspace / Resource Invite：

```text
未登录
↓
Login / Register
↓
验证邀请仍有效
↓
Accept Invite
```

Invite 本身不自动创建认证 Session。

---

## 112. Invite Email Match

如果 Invite 指定邮箱：

```text
接受邀请的 Account
```

必须满足对应邮箱策略。

不能让任意已登录用户拿到链接就接受一个定向邀请。

---

## 113. Anonymous Share 与 Invite

Share Link：

```text
匿名只读
```

Invite：

```text
加入成员关系
```

两者不能混淆。

Share 不自动成为 Member。

---

## 114. Auth 与 Rate Limit

Auth Rate Limit 独立于普通 API Rate Limit。

重点保护：

```text
login
register
password reset
provider callback
email verification
account recovery
```

---

## 115. Email Send Queue

邮件发送：

```text
verification
reset
security notification
```

建议通过：

```text
Async Queue
```

处理。

但 Reset / Verify 状态本身需要先可靠记录。

---

## 116. Email 重复发送

重复点击：

```text
Send Verification
Reset Password
```

必须限流。

避免：

```text
邮件轰炸
资源滥用
```

---

## 117. Email Token Lifecycle

Email Verification Token 和 Reset Token：

```text
短期
单次
可撤销
```

新 Token 创建后：

```text
旧 Token
```

可以按策略失效。

---

## 118. Account Lifecycle

第一版 Account 至少支持：

```text
PendingVerification
Active
Disabled
PendingDeletion
Deleted
```

仅通过微信 / 飞书创建、尚未绑定 verified recovery email 的 Provider-only Account 第一版可以直接进入 `Active`。

系统持续提示：

```text
Add Recovery Email
```

但 Recovery Email 不是 Provider-only Account 进入 Active 的前置条件。

---

## 119. Session Lifecycle

Session 至少支持：

```text
Active
Replaced
LoggedOut
Expired
Revoked
```

客户端根据原因展示不同提示。

---

## 120. Session Reason

Session 失效应记录：

```text
reason
```

例如：

```text
NewDeviceLogin
UserLogout
PasswordReset
AccountDisabled
Expired
SecurityRevoke
```

有利于：

- 用户提示
- Audit
- Debug

---

## 121. Device Session 状态机

核心流程：

```text
0 Active
↓ Login A
1 Active
↓ Login B
2 Active
↓ Login C
2 Active
├── C becomes Active
└── oldest Active Session → Replaced
```

任意时刻：

```text
Active Device Session Count ≤ 2
```

同一浏览器多个 Tab 共享同一个 Device Session。

---

## 122. PostgreSQL 约束

PostgreSQL 必须保证 Email Identity、Provider Identity 唯一，并让 Active Device Session Count ≤ 2 的并发登录结果可以通过事务 / 锁 /约束或等价原子机制确定。

不能只依赖应用层 `if count < 2`。

---

## 123. 并发新登录

多个设备并发登录时，最终必须确定：

```text
最多 2 个 Active Device Sessions
超限 Session 按确定规则替换最旧 Active Session
```

不能出现 3 个长期 Active Session，也不能随机踢掉所有既有设备。

---

## 124. Auth Service 多实例

Auth Service 必须支持多实例。

不能依赖：

```text
本机 Memory
```

决定：

```text
当前 Active Session
```

权威状态在：

```text
PostgreSQL
```

Cache / Event 用于加速传播。

---

## 125. Session Cache

可以使用 Cache 加速：

```text
Session Validation
```

但：

```text
SessionReplaced
SessionRevoked
AccountDisabled
```

必须触发可靠失效。

高风险操作可以回源权威状态。

---

## 126. Session Event Reliability

Session 失效 Event 如果暂时延迟：

```text
下游服务
```

不能永久保持旧授权。

需要：

```text
event invalidation
+
short cache TTL
+
critical recheck
```

形成多层保护。

---

## 127. Observability

至少监控：

```text
registration count
registration failure
email verification rate
login success
login failure
password reset count
password reset failure
wechat login success / failure
feishu login success / failure
provider callback error
session created
session replaced
session invalidation lag
account disabled
rate limit hit
suspicious login
email send failure
```

---

## 128. Security Alert

至少对以下行为提供安全告警能力：

```text
大量登录失败
异常 Provider Callback
同 Account 高频 Session Replacement
Password Reset 异常
大量注册
大量 Share Link 匿名访问
Account Disable / Delete
```

---

## 129. Audit

至少记录：

```text
账号创建
邮箱验证
密码修改
密码重置
邮箱修改
微信绑定 / 解绑
飞书绑定 / 解绑
新设备登录替换旧 Session
账号禁用
账号删除请求
账号最终删除
```

---

## 130. 第一版不做

第一版明确不做：

```text
MFA
TOTP
Passkey
多设备同时在线
GitHub Login
Google Login
Microsoft Login
Apple Login
QQ Login
匿名编辑
匿名评论
Support Impersonation
企业 SAML
企业 SCIM
复杂 Device Trust
Biometric Login
```

以后如果产品战略变化：

```text
单独新设计
```

不能在当前实现里偷偷保留一半未完成机制。

---

## 131. 核心验收场景

### 场景 1：邮箱注册

用户：

```text
输入邮箱 + 密码
↓
注册
↓
收到验证邮件
↓
完成验证
```

结果：

```text
Account Active
```

---

### 场景 2：重复邮箱注册

两个请求同时注册同一邮箱。

结果：

```text
PostgreSQL 最终只有一个有效 Email Identity
```

不能产生重复账号。

---

### 场景 3：微信首次登录

用户微信授权成功。

结果：

- 正确识别 Provider Identity
- 创建或绑定 Account
- 创建唯一 Active Session
- 业务系统只看到 userId

---

### 场景 4：飞书首次登录

与微信相同：

```text
Feishu Identity
↓
Account
↓
Session
```

Provider 字段不泄漏到业务身份模型。

---

### 场景 5：绑定微信

邮箱账号已登录。

用户绑定微信。

结果：

- 微信 Identity 绑定到当前 Account
- 以后微信登录进入同一个 userId
- 产生安全通知 / Audit

---

### 场景 6：Provider 冲突

某微信 Identity 已绑定 Account A。

Account B 尝试绑定。

结果：

```text
拒绝
```

不能同一 Provider Identity 绑定多个 Account。

---

### 场景 7：新设备登录

Device A 已登录。

Device B 登录成功。

结果：

```text
Session B → Active
Session A → Replaced
```

A 的 API / WebSocket 很快失效。

---

### 场景 8：旧设备正在编辑

Device A 正在多人协作文档。

Device B 登录。

结果：

- Device A 收到 SessionReplaced
- 当前认证 Subscription 关闭
- 本地未同步内容不被静默删除
- Device B 可以正常登录

---

### 场景 9：并发登录

A、B 两个设备几乎同时登录。

结果：

```text
最终只有一个 Active Session
```

不能双活。

---

### 场景 10：Password Reset

用户忘记密码。

完成 Reset。

结果：

- 新密码生效
- 所有旧 Session 失效
- Reset Token 单次失效
- 可以安全重新登录

---

### 场景 11：旧 Reset Link 重放

Reset Token 已使用。

攻击者再次访问。

结果：

```text
拒绝
```

---

### 场景 12：Provider 故障

微信登录暂时不可用。

结果：

```text
邮箱 + 密码
飞书
```

仍然可用。

核心 Account 系统不宕机。

---

### 场景 13：匿名只读 Share

未登录用户打开 Read Share Link。

结果：

- 可以读取允许内容
- 不创建正式 Account
- 不能编辑
- 不能评论

---

### 场景 14：匿名用户点击评论

匿名 Viewer 点击：

```text
Comment
```

结果：

```text
要求 Login / Register
```

登录后重新计算权限。

---

### 场景 15：Share Link Revoke

匿名用户正在阅读。

Owner 撤销 Share Link。

结果：

- 新读取失败
- 当前匿名 Subscription 失效
- 不继续长期接收内容

---

### 场景 16：Account Disabled

管理员 / 安全系统禁用账号。

结果：

- 当前 Session 立即失效
- Realtime 断开
- 新登录拒绝
- 已存在 Resource 不被物理删除

---

### 场景 17：Account Delete

用户请求删除账号。

结果：

- 进入 PendingDeletion
- 检查 Owned Workspace
- 不直接删除 Workspace Resource
- Grace Period 后执行最终账号删除

---

### 场景 18：高风险账号设置

用户修改邮箱。

Session 已经很久没有重新认证。

结果：

```text
要求 Recent Re-authentication
```

不是 MFA。

---

### 场景 19：OAuth State 攻击

攻击者伪造微信 / 飞书 Callback。

结果：

```text
State / Callback Validation 失败
```

不能创建登录 Session。

---

### 场景 20：Session Cache 延迟

旧设备被替换后某实例 Cache 暂未立即刷新。

结果：

- Invalidation Event 传播
- Cache TTL 兜底
- 高风险写入可重新检查权威 Session
- 旧 Session 不能长期继续使用

---

## 132. 本地 AI 实现自由度

本设计不规定：

- Password Hash 库具体实现
- Session Token 格式
- Cookie 名称
- Session Expiry 具体天数
- Cache 产品
- Email Provider
- 微信 SDK
- 飞书 SDK
- OAuth Library
- Captcha Provider
- Risk Engine 产品
- Auth Service 是否独立微服务
- Account / Session 数据表数量
- Session Version 字段具体名称

本地 AI 可以根据当前技术栈和部署环境选择。

但必须满足本设计的最多 2 个活跃设备 Session、Session 失效、Provider 安全、邮箱恢复、匿名只读 Share 和生产安全要求。

---

## 133. 架构硬约束

1. Account 使用稳定 userId 作为系统长期身份。
2. Email / WeChat / Feishu 都只是 Identity，不替代 userId。
3. 第一版登录方式只有邮箱密码、微信、飞书。
4. 第一版自由注册。
5. 第一版不做 MFA，后续当前规划也不引入 MFA。
6. 第一版每个 Account 最多允许 2 个 Active Device Sessions。
7. 第 3 个设备登录成功后必须替换最旧的 Active Device Session；同一浏览器多个 Tab 不额外占用设备名额。
8. Session Replacement 必须实时影响 API 与 Realtime。
9. 旧设备本地未同步内容不能被静默删除。
10. Session 权威状态必须可服务端撤销，不能依赖不可撤销长期 Token。
11. Account / Session 权威数据使用 PostgreSQL。
12. Provider Identity 必须唯一绑定 Account。
13. Provider 回调必须防 CSRF / replay / redirect abuse。
14. 微信 / 飞书 Secret 不得进入前端、Git 或普通日志。
15. Password 必须使用成熟 Password Hash。
16. Password Reset / Email Verification Token 必须短期、单次、可撤销。
17. 修改密码、邮箱、Provider Binding 等高风险账号操作需要 Recent Re-authentication。
18. Auth 与 Permission 必须职责分离。
19. Share Link 支持匿名只读，但匿名不能编辑或评论。
20. 匿名 Share Actor 不是正式 Account。
21. Share Link 撤销必须使匿名当前访问失效。
22. 第三方 Provider 故障不能让邮箱登录不可用。
23. Session Cache 必须具备可靠失效与权威回源能力。
24. Auth Service 必须支持多实例，不能依赖单机 Memory 保证 Active Device Session Count ≤ 2。
25. Account Delete 不直接删除 Workspace Resource。
26. 所有关键账号安全操作必须 Audit。
27. Auth / Session 模块遵守 Unified Module Communication Design。

---

## 134. 最终模型

```text
                 Account
                   │
                   ├── Email Identity
                   ├── WeChat Identity
                   └── Feishu Identity
                   │
                   ▼
                userId
                   │
                   ▼
             Active Session
                   │
                   ├── API
                   ├── Realtime
                   ├── AI
                   └── Plugin
```

设备上限：

```text
Device A Login → Session A Active
Device B Login → Session B Active
Device C Login → Session C Active
                  + oldest(A) Replaced

B remains Active
```

匿名 Share：

```text
Share Link
↓
Anonymous Read Actor
↓
Read-only Resource Access

Edit / Comment
↓
Login / Register
↓
Account Permission
```

系统必须保证：

> Auth 只解决“你是谁”，Permission 决定“你能做什么”；微信和飞书只是登录入口，真正长期身份仍然是 userId；设备 Session 上限策略由服务端 Session 权威状态保证，新设备可以登录，旧设备会被可靠踢下线。
