# Permission & Access Control Design

## 1. 目标

本设计定义系统中 Workspace、Project、Resource、Realtime Collaboration、Share、AI、Plugin 和 History 共同遵守的权限体系。

目标不是实现一个 Demo 级“能不能打开文件”的权限判断，而是提供可以上线运行的访问控制能力：

- 用户能够清楚地知道自己能做什么
- 管理者能够邀请、移除和调整成员权限
- 分享链接可以安全创建、撤销和过期
- 权限变化能够立即影响正在进行的实时协作
- AI 和 Plugin 不能绕过用户权限
- 服务端不依赖前端 UI 做安全判断
- 多实例部署、缓存和高并发情况下仍保持权限结果一致
- 所有高风险权限操作可以审计
- 权限系统能够继续扩展，而不会污染 Resource、Yjs 或 Block 模型

---

## 2. 产品权限级别

第一版正式支持五个权限级别：

```text
Owner
Manage
Edit
Comment
Read
```

### Owner

拥有当前协作对象的最高管理权限。

至少可以：

- 查看内容
- 编辑内容
- 评论
- 管理成员
- 管理分享
- 修改权限
- 转移 Owner
- 删除或恢复允许删除的对象
- 查看权限审计

Owner 必须始终可明确识别。

---

### Manage

用于日常协作管理。

至少可以：

- 查看内容
- 编辑内容
- 评论
- 邀请成员
- 移除普通成员
- 修改普通成员权限
- 创建和管理分享链接
- 查看必要的协作管理信息

不能执行只允许 Owner 的最高级操作，例如：

- 转移 Owner
- 移除 Owner
- 执行平台定义的不可逆最高权限操作

---

### Edit

可以：

- 查看内容
- 编辑 Resource
- 参与实时协作
- 评论

不能管理成员或分享权限。

---

### Comment

可以：

- 查看内容
- 查看实时变化
- 创建评论
- 回复评论

不能修改 Resource 正文。

---

### Read

可以：

- 查看 Resource
- 接收实时内容变化
- 查看允许展示的协作状态

不能：

- 修改正文
- 创建评论
- 管理成员
- 修改分享设置

---

## 3. 权限继承

Workspace / Project 可以提供上层权限。

Resource 最终产生当前用户的有效权限。

系统应支持：

```text
上层默认权限
+
Resource 自身设置
↓
Effective Permission
```

Resource 可以使用上层权限，也可以通过自身设置形成独立访问范围。

用户不需要理解复杂 ACL 合并规则。

产品层应表现为简单的：

```text
继承当前项目权限
或
自定义当前 Resource 权限
```

工程实现不得把复杂的 allow / deny 规则直接暴露给普通用户。

---

## 4. Resource 是实际执行边界

所有实际内容访问和实时协作操作，都必须基于当前 Resource 的有效权限。

例如：

```text
打开 Resource
加入实时协作
发送 Yjs Update
创建评论
调用 AI 修改 Resource
Plugin 写入 Resource
查看 Resource History
创建 Resource Share
```

都必须基于同一份有效权限结果。

不同模块不得自己维护平行的权限判断逻辑。

---

## 5. 成员管理

系统必须支持：

- 邀请成员
- 查看成员
- 修改成员权限
- 移除成员
- 转移 Owner
- 查看待接受邀请
- 取消未接受邀请
- 处理已失效邀请

邀请可以作用于：

- Workspace
- Project
- Resource

具体邀请入口可以根据产品 UI 调整，但底层必须统一进入权限系统。

---

## 6. 邀请状态

邀请至少应支持以下状态：

```text
Pending
Accepted
Expired
Revoked
```

要求：

- 重复点击邀请不会创建无限重复记录
- 已撤销邀请不能继续使用
- 已过期邀请不能继续加入
- 用户接受邀请时重新检查邀请是否仍有效
- 邀请权限不能超过邀请者自己的管理能力

---

## 7. 分享链接

第一版支持分享链接。

分享链接至少支持：

```text
Read
Comment
Edit
```

是否允许某种权限由当前操作者自己的权限决定。

分享链接至少具备：

- 创建
- 复制
- 查看当前状态
- 修改访问级别
- 设置有效期
- 立即撤销
- 重新生成
- 查看是否已失效

分享链接被撤销或过期后，已有访问不能继续被视为有效授权。

---

## 8. Guest

系统支持 Guest。

Guest 用于：

- 不属于 Workspace 的临时协作者
- 通过邀请加入某个 Project 或 Resource 的外部用户
- 通过受控分享访问内容的登录用户

Guest 不应因为获得某个 Resource 权限而自动获得整个 Workspace 的访问能力。

Guest 的可见范围必须保持最小化。

---

## 9. 匿名访问

第一版已确定支持：

```text
Share Link 匿名只读
```

并明确不支持：

```text
Anonymous Edit
Anonymous Comment
```

匿名 Share Actor 不是 Workspace Member，也不是正式 Account。其能力只能来自当前有效 Share Link；Share Link 被撤销或过期后，当前匿名访问和相关只读 Subscription 必须失效。

第一版匿名 Viewer 不展示内部 Comment Thread，也不参与匿名 Presence；Share Link 只授予 Resource Content Read。

---

## 10. 实时协作权限

Realtime Collaboration 必须实时消费权限结果。

Subscribe Resource 时必须检查：

```text
当前用户
+
当前 Resource
+
当前有效权限
```

只有拥有 `Edit` 或更高权限的用户才能向共享 Resource 提交正文 Yjs Update。

`Comment` 和 `Read` 用户可以接收正文同步，但不能提交正文修改。

---

## 11. 运行中权限变化

权限变化必须影响已经在线的用户。

例如：

```text
Edit
↓
Read
```

用户无需刷新页面。

系统必须：

- 通知当前 Resource Session 权限已变化
- 停止接受该用户新的正文修改
- 更新前端可用功能
- 保留用户仍允许访问的实时读取能力

如果权限变为：

```text
None
```

则当前 Resource Subscription 必须失效。

用户不应继续接收该 Resource 的实时内容。

---

## 12. 被移除用户

用户被移除后：

- 新请求立即失去访问能力
- 当前实时 Subscription 失效
- 当前分享授权失效
- 不再接收该 Resource 的实时正文和 Presence
- 已经存在的客户端缓存不能继续作为授权依据

客户端本地仍可能存在之前读取过的数据。

系统不能承诺擦除用户设备上已经获取的数据，但必须阻止继续访问和同步。

---

## 13. 权限降低时的本地未同步修改

如果用户：

```text
离线编辑
↓
期间权限被从 Edit 降为 Read
↓
重新连接
```

本地未同步修改不能写入共享 Resource。

但系统也不能静默删除这些本地修改。

产品应允许至少一种安全处理方式：

- 复制本地内容
- 导出本地修改
- 等待权限恢复后重新同步

具体 UI 由产品层决定。

---

## 14. 前端职责

前端根据权限结果：

- 显示或隐藏管理入口
- 禁用不允许的编辑能力
- 显示只读 / 评论状态
- 响应实时权限变化
- 给用户明确反馈

但：

> 前端权限只能用于产品体验，不能作为最终安全边界。

任何危险操作仍必须由服务端再次验证。

---

## 15. 服务端职责

服务端是权限执行的安全边界。

至少必须验证：

- Resource 是否存在
- 当前用户身份是否有效
- 当前请求所需权限
- 当前权限是否仍然有效
- 分享链接是否仍有效
- 邀请是否仍有效
- 当前实时 Subscription 是否仍有对应能力

客户端提交：

```text
userId
role
permission
```

不能被直接信任。

用户身份必须来自可信认证上下文。

---

## 16. 统一权限服务

系统需要一个统一的权限判定能力。

其他模块只能询问：

```text
当前主体对当前 Resource 可以做什么？
```

不得出现：

```text
Realtime 自己算一套
AI 自己算一套
Plugin 自己算一套
History 自己算一套
Share 自己算一套
```

否则不同模块最终会产生不一致授权。

统一权限能力至少需要支持：

- 查询 Effective Permission
- 判断某个 Action 是否允许
- 权限变化通知
- 缓存失效
- 高风险操作审计

具体函数、类和接口由本地 AI 根据项目结构实现。

---

## 17. 权限能力而不是散落 Role 判断

产品对用户展示：

```text
Owner
Manage
Edit
Comment
Read
```

但内部业务模块不应到处写：

```text
if role == "Edit"
```

每个业务行为应根据能力判断。

例如：

```text
canRead
canEdit
canComment
canManageMembers
canManageShare
canTransferOwner
```

这样以后新增权限级别或企业策略时，不需要修改所有业务模块。

Role 负责给用户一个容易理解的权限套餐。

Capability 负责工程执行。

---

## 18. AI 权限

AI 不能拥有绕过用户权限的特殊通道。

用户触发 AI 修改：

```text
User
↓
AI Task
↓
Resource Change
```

最终写入能力不能超过该任务被授权的范围。

如果用户只有：

```text
Read
```

AI 不能因为运行在服务端就修改 Resource。

---

## 19. AI 长任务中的权限变化

AI Task 可能运行较长时间。

如果运行期间：

```text
用户权限被撤销
Resource 被删除
Resource 被设为只读
```

AI 在最终写入前必须重新确认权限和目标有效性。

不能只在任务创建时检查一次。

---

## 20. Plugin 权限

Plugin 同样不能天然拥有全部 Resource 权限。

Plugin 操作需要受：

```text
用户授权
+
Plugin 自身授权范围
+
Resource 当前权限
```

共同限制。

实际可执行能力取三者允许范围的交集。

---

## 21. Plugin 最小权限

Plugin 应遵循最小权限原则。

例如一个只需要读取文档的 Plugin：

```text
不应自动获得 Edit
```

一个只需要当前 Project 的 Plugin：

```text
不应自动获得整个 Workspace
```

具体 OAuth / Plugin Permission 模型由 Plugin 模块进一步设计。

---

## 22. Comment 权限

Comment 是独立产品能力。

至少：

```text
Comment
Edit
Manage
Owner
```

可以创建评论。

`Read` 默认只能查看允许展示的评论。

Comment 权限不能隐式获得正文编辑能力。

---

## 23. History 权限

查看 History 与执行 Restore 都必须使用统一 Permission Capability，不能由 History 模块自行维护一套 Role。

第一版普通 History Viewer / Restore Capability 为：

```text
Edit
Manage
Owner
```

统一 Capability 至少表达：

```text
canViewHistory
canRestoreHistory
```

History 不能成为绕过当前 Resource Read Permission 的入口。

---

## 24. Trash / Restore / Purge 权限

Trash、Restore 和 Purge 属于不同风险等级，并必须映射为独立 Capability。

第一版权限固定为：

```text
Trash   = Manage / Owner
Restore = Manage / Owner
Purge   = Owner only
```

统一 Capability 至少表达：

```text
canTrash
canRestore
canPurge
```

`Purge` 始终视为最高风险能力，并保持独立确认、审计和服务端鉴权；不得把三种操作合并成一个 `Delete` 权限。

---

## 25. Owner 保护

系统必须始终避免：

```text
Resource 没有 Owner
```

或：

```text
唯一 Owner 被普通成员直接移除
```

Owner 转移必须是明确操作。

转移过程中需要防止：

- 重复提交
- 并发转移
- 目标用户已被移除
- 目标用户无有效身份
- 转移一半失败导致双重或无 Owner

具体事务实现由本地 AI 选择。

---

## 26. 权限并发修改

多个管理者可能同时修改成员权限。

系统必须保证最终状态可确定。

例如：

```text
Admin A 把 User X 改为 Edit
Admin B 同时移除 User X
```

不能产生：

```text
数据库说已移除
Realtime 仍认为可以 Edit
```

权限写入、缓存和实时 Session 必须最终一致。

具体乐观锁、事务或串行策略由实现选择。

---

## 27. 权限缓存

生产环境允许缓存权限结果以降低高频查询成本。

但缓存必须具备明确失效机制。

权限发生变化后：

```text
旧缓存不能长时间继续授权
```

高风险写操作不能仅依赖长期缓存。

系统应支持：

- 本地缓存
- 分布式缓存
- 事件驱动失效
- TTL 兜底

具体实现由部署架构决定。

---

## 28. 权限变化事件

权限系统必须能够发布权限变化。

至少覆盖：

```text
member added
member removed
permission changed
owner transferred
share revoked
share expired
resource access mode changed
```

Realtime Collaboration、Share、AI、Plugin 等模块可以据此及时失效自己的授权上下文。

不要依赖客户端主动刷新权限。

---

## 29. 多实例部署

在多服务实例环境中：

```text
Server A
Server B
Server C
```

用户权限变化必须传播到所有可能持有相关 Resource Session 的实例。

例如：

```text
用户在 Server A 被降权
```

不能让连接在 Server B 的实时客户端继续长期写入。

具体事件总线、缓存和分布式同步技术由实现决定。

---

## 30. 分享链接安全

分享链接不能只使用容易猜测的自增 ID。

要求：

- Token 具备足够随机性
- 服务端只保存安全形式
- 支持撤销
- 支持过期
- 支持权限级别
- 支持限流
- 支持审计
- 不在日志中明文泄露完整 Token
- 不把完整 Token 发送给无关模块

是否绑定登录、邮箱、域名或密码，可以作为后续企业策略扩展。

---

## 31. 邀请安全

邀请链接同样需要：

- 随机 Token
- 过期时间
- 单次或受控使用
- 撤销
- 接受时再次检查
- 防止权限提升
- 防止邀请者在失去权限后，旧邀请仍继续授权

---

## 32. 防止越权

服务端必须防止：

```text
修改 resourceId
↓
访问别人的 Resource
```

以及：

```text
伪造 subscriptionId
伪造 userId
重放已撤销 Share Token
重放旧 Invitation
越权调用 AI 写入
越权 Plugin 写入
```

所有资源访问都必须重新绑定：

```text
可信身份
+
目标 Resource
+
当前有效能力
```

---

## 33. 审计日志

以下事件必须进入安全审计：

- 邀请成员
- 接受邀请
- 移除成员
- 修改权限
- Owner 转移
- 创建分享链接
- 修改分享级别
- 撤销分享
- 重要权限拒绝
- AI / Plugin 的高权限写入
- 永久删除等高风险管理操作

审计日志不能依赖 Y.Doc。

它属于独立的安全与管理数据。

---

## 34. 审计日志要求

至少需要记录：

```text
谁
什么时候
对哪个对象
执行了什么权限相关操作
结果是什么
```

必要时还应记录：

- 来源 Client
- 请求 ID
- 分享 / 邀请来源
- 操作前后权限变化摘要

但不能在审计日志中记录：

```text
密码
完整分享 Token
认证密钥
不必要的正文内容
```

---

## 35. 幂等性

以下操作必须能够应对重复请求：

- 邀请
- 接受邀请
- 修改权限
- 移除成员
- 创建 / 撤销分享
- Owner 转移
- 权限变化通知

用户双击按钮、网络重试或服务重放不能造成：

```text
重复成员
重复 Owner
重复邀请
权限状态异常
```

具体 Idempotency Key 或事务实现由本地 AI 选择。

---

## 36. Rate Limit

以下接口需要独立限流：

- 创建邀请
- 创建分享链接
- 权限查询异常高频
- 权限修改
- 分享 Token 验证
- 邀请 Token 验证
- AI / Plugin 高权限操作

限流不能阻塞正常实时正文同步。

具体阈值由压力测试与部署环境确定。

---

## 37. 故障行为

权限服务短暂不可用时：

### 已存在的只读会话

可以根据安全策略短时间继续读取已授权内容。

### 新的高风险写操作

不能默认放行。

### 权限管理操作

不能在未知权限状态下假装成功。

原则：

> 权限状态不确定时，高风险行为 Fail Closed。

不能因为权限服务异常就默认：

```text
Allow All
```

---

## 38. 权限与 Resource 删除

Resource 被删除或进入不可访问状态后：

- 新访问立即拒绝
- 当前 Subscription 根据产品规则关闭
- AI / Plugin 新写入拒绝
- Share Link 不再继续授权
- History / Trash 根据对应权限规则处理

Resource 生命周期变化必须能够触发权限上下文失效。

---

## 39. 可观测性

至少监控：

```text
permission check latency
permission cache hit rate
permission cache invalidation
permission denied count
active shared links
expired / revoked link access
invitation accept / failure
runtime permission downgrade
subscription revoked count
AI permission denied
plugin permission denied
permission event propagation latency
audit write failure
```

权限事件传播过慢会直接造成越权窗口。

需要作为生产指标监控。

---

## 40. 必须避免

不得：

- 只依赖前端按钮控制权限
- 把权限写进 Y.Doc
- 让 AI 以系统身份绕过用户权限
- 让 Plugin 默认拥有所有 Resource 权限
- 让不同业务模块维护各自的 Role 规则
- 分享链接撤销后继续长期有效
- 只在 WebSocket 建连时检查一次权限
- 用长期缓存代替实时权限失效
- 让被移除用户继续保持 Subscription
- 把 Guest 权限自动扩展到整个 Workspace
- 允许唯一 Owner 被普通删除操作移除
- 在权限服务未知状态下默认允许高风险写操作
- 为 Block 单独建立第一版权限系统

---

## 41. 第一版不做

第一版暂不设计：

```text
Block 级权限
字段级权限
复杂 Allow / Deny Policy DSL
ABAC Policy Language
匿名正文编辑
企业组织级合规策略
IP 白名单
设备信任策略
地域访问策略
数据防泄漏规则
```

这些能力可以后续在统一权限服务上扩展。

第一版不能因为未来可能需要这些能力，就提前把权限系统设计成复杂策略引擎。

---

## 42. 核心验收场景

### 场景 1：普通编辑

Edit 用户打开 Resource。

结果：

- 可以加入实时协作
- 可以发送 Yjs Update
- 可以评论
- 不能管理成员

---

### 场景 2：只读用户

Read 用户打开同一个 Resource。

结果：

- 可以实时看到其他人的更新
- 不能修改正文
- 不能通过手工构造网络请求绕过只读限制

---

### 场景 3：评论用户

Comment 用户：

- 可以查看内容
- 可以评论
- 不能修改正文

---

### 场景 4：运行中降权

Edit 用户正在输入。

管理员将其改为 Read。

结果：

- 不需要刷新页面
- 新正文 Update 不再被接受
- 前端进入只读状态
- 仍可以接收允许的实时内容

---

### 场景 5：运行中移除

用户正在 Resource 中协作。

管理员移除该用户。

结果：

- 当前 Subscription 立即失效
- 不再接收新正文
- 不再提交正文
- 其他 Resource 不受影响

---

### 场景 6：分享链接撤销

用户通过 Edit 分享链接进入。

Owner 撤销链接。

结果：

- 新访问立即失败
- 已有基于该链接建立的授权失效
- 不能依赖旧缓存继续编辑

---

### 场景 7：分享链接过期

达到有效期以后：

- 新访问拒绝
- 已有依赖该链接的授权按产品策略失效
- 审计可确认过期原因

---

### 场景 8：Guest

Guest 只被邀请到 Resource A。

结果：

```text
Resource A → 可以访问
Resource B → 不可访问
Workspace 其他内容 → 不可访问
```

---

### 场景 9：AI 越权防护

Read 用户请求 AI 修改 Resource。

结果：

```text
AI 可以理解允许读取的内容
但不能提交正文修改
```

---

### 场景 10：AI 长任务降权

Edit 用户发起 AI 修改。

AI 生成期间用户被降为 Read。

最终写入时：

```text
重新检查
↓
拒绝写入
```

不能因为任务创建时有 Edit 就继续写入。

---

### 场景 11：Plugin 最小权限

只读 Plugin 被授权访问 Resource。

结果：

- 可以读取允许内容
- 不能提交 Yjs Update
- 不能创建新的 Share

---

### 场景 12：Owner 转移

Owner 把所有权转移给另一个有效成员。

结果：

- 新 Owner 唯一确定
- 原 Owner 权限根据产品规则调整
- 中途重试不产生双 Owner 或无 Owner
- 操作有审计

---

### 场景 13：服务端多实例

User A 在 Server A 修改 User B 权限。

User B 当前连接 Server B。

结果：

> Server B 的权限上下文及时失效，User B 的实时能力发生对应变化。

---

### 场景 14：恶意请求

Read 用户直接构造正文 Update 请求。

结果：

```text
Server 拒绝
```

前端状态不影响安全结论。

---

### 场景 15：离线编辑后降权

用户离线期间修改内容。

管理员把其权限降为 Read。

用户恢复连接。

结果：

- 本地修改不能进入共享 Resource
- 本地内容不能被静默删除
- 用户可以复制 / 导出或等待权限恢复

---

### 场景 16：权限服务异常

权限服务短暂不可用。

结果：

- 不默认放行新的高风险修改
- 不出现 Allow All
- 系统进入可观测的 Degraded 状态

---

## 43. 与其他模块的边界

### Resource Collaboration

负责：

```text
Resource 是什么
Resource 如何成为协作边界
```

Permission 提供 Resource 的访问结果。

---

### Realtime Collaboration Protocol

负责：

```text
Subscription
Sync
Awareness
Connection
```

Permission 决定：

```text
是否可以 Subscribe
是否可以发送正文 Update
权限变化后 Subscription 如何失效
```

---

### Persistence

负责：

```text
可靠保存当前 Resource 状态
```

Permission 不进入 Yjs 正文持久化。

---

### History

负责：

```text
版本
Diff
Restore
Audit Product View
```

Permission 决定谁可以查看或执行相关能力。

---

### AI / Plugin

负责：

```text
业务能力
自动化
内容修改
```

Permission 限制其最终可执行范围。

---

## 44. 架构硬约束

1. 第一版产品权限为 `Owner / Manage / Edit / Comment / Read`。
2. Workspace / Project 权限可以向下继承，但 Resource 产生最终有效权限。
3. 所有实际 Resource 操作都必须基于统一权限结果。
4. 前端权限只负责体验，服务端负责最终安全判断。
5. Realtime、AI、Plugin、History、Share 不得维护独立权限体系。
6. 业务执行尽量使用 Capability，而不是散落的 Role 判断。
7. 权限变化必须实时影响当前 Resource Session。
8. 被移除用户的当前 Subscription 必须失效。
9. 分享链接必须可撤销、可过期、可审计。
10. 第一版支持 Guest；Share Link 支持匿名只读，但匿名不得编辑或评论。
11. AI 和 Plugin 的写入能力不得超过实际授权范围。
12. 长任务最终写入前必须重新确认权限。
13. 权限可以缓存，但必须有可靠的失效和传播机制。
14. 多实例环境下权限变化必须传播到所有相关协作实例。
15. 高风险操作在权限状态不确定时必须 Fail Closed。
16. 权限不能存入 Y.Doc。
17. 权限管理操作必须可审计并具备幂等保护。
18. 唯一 Owner 不能被普通成员移除流程破坏。
19. Guest 权限必须保持最小访问范围。
20. 第一版不实现 Block 级权限和复杂 Policy DSL。

---

## 45. 最终产品能力

第一版权限系统交付后，用户应当能够完成：

```text
创建协作空间
↓
邀请成员
↓
分配权限
↓
共同编辑 / 评论 / 查看
↓
创建分享链接
↓
邀请 Guest
↓
实时调整权限
↓
立即影响正在协作的用户
↓
撤销成员或分享权限
↓
查看必要的权限审计
```

与此同时：

```text
Realtime
AI
Plugin
History
Share
```

都使用同一个权限结果。

权限系统应当像基础设施一样存在，而不是每增加一个模块就重新设计一次。
