# Architecture Docs Index

这是当前最新版本的架构设计文档集合。

> **读取规则：先读 `00-ARCHITECTURE-CONSTITUTION.md`，再读当前任务的 Canonical Owner 和直接依赖。不要默认把全部文档塞进本地 AI 上下文。**

## 文档顺序

0. `00-ARCHITECTURE-CONSTITUTION.md`  
   定义全系统最高级不变量、Canonical Owner、冲突解决顺序、稳定生命周期词汇和本地 AI 加载规则。

1. `01-Block-Design.md`  
   定义 Document 内部的内容模型、Block / Node / Schema、Yjs 与编辑器的关系。

2. `02-Node-Identity-Design.md`  
   定义 `nodeId`、`NodeRef`、节点身份生命周期，以及跨模块定位规则。

3. `03-Resource-Collaboration-Design.md`  
   定义 `Resource` 作为系统唯一实时协作边界。

4. `04-Unified-Module-Communication-Design.md`  
   系统所有模块共同遵守的通信总规范，统一 `Command / Query / Event / Stream`。

5. `05-Realtime-Collaboration-Protocol-Design.md`  
   统一通信体系中的实时 Stream 子协议，负责 Yjs、Awareness、Session、重连、背压等。

6. `06-Persistence-Design.md`  
   定义 Durable Update Journal、Checkpoint、Compaction、恢复与本地恢复。

7. `07-Permission-Access-Control-Design.md`  
   定义 Owner / Manage / Edit / Comment / Read、分享、Guest、实时权限变化和安全约束。


8. `08-History-Version-Restore-Design.md`  
   定义自动历史、命名版本、历史预览、Diff、安全恢复、恢复可逆、Retention 与历史故障隔离。

9. `09-Workspace-Project-Resource-Lifecycle-Design.md`  
   定义 Workspace / Project / Folder / Resource 的创建、组织、移动、复制、Trash、Restore、Purge 与生命周期联动。

10. `10-Asset-File-Storage-Design.md`  
    定义图片、视频、附件等二进制文件的上传、Object Storage、预览、安全扫描、引用、去重、权限与垃圾回收。

11. `11-Search-Index-Design.md`  
    定义 Workspace / Project / Resource 的全文搜索、中文与多语言索引、权限过滤、实时增量索引、Reindex、可选语义搜索与故障隔离。

12. `12-AI-Task-ChangeSet-Design.md`  
    定义 AI Task、Context、Tool、ChangeSet、多 Resource 修改、Preview、Apply、冲突处理、权限、重试、取消与安全边界。

13. `13-Import-Export-Design.md`  
    定义单 Resource、Folder、Project 的 Import / Export、格式 Adapter、Preview、Identity Mapping、Asset、安全转换、批量任务与数据可移植性。

14. `14-Observability-Operations-Design.md`  
    定义 Logs、Metrics、Traces、Audit、Health、Alert、Dashboard、Runbook、Operations Console、容量监控与生产故障恢复。

15. `15-Deployment-Scaling-Disaster-Recovery-Design.md`  
    定义 PostgreSQL 生产拓扑、多实例部署、Resource 分片、水平扩缩容、滚动发布、Backup、PITR、RPO / RTO 与区域级灾难恢复。

16. `16-Account-Auth-Session-Design.md`  
    定义邮箱密码、微信 / 飞书登录、最多 2 个活跃设备 Session、超限替换最旧设备、账号恢复、匿名只读 Share 与 Auth 安全边界。

17. `17-Comment-Mention-Notification-Design.md`  
    定义整篇 Resource / Node / 文本范围评论、Thread、Reply、Resolve、@具体用户、评论 Tombstone、站内通知、未读状态与稳定跳转。

18. `18-Client-API-Frontend-Integration-Design.md`  
    定义官方桌面 Web / 移动端基础体验、Client Contract、前后端统一通信、Local Y.Doc、离线编辑、多 Tab、Client SDK、缓存与错误恢复。

19. `19-Frontend-Module-Contract-Design.md`  
    定义前端功能模块、每个模块依赖的 Command / Query / Event / Stream、Server / Local / Runtime State，以及 UI / UX 与系统 Contract 的职责边界。

20. `20-API-Gateway-External-Integration-Design.md`  
    定义 Client / Realtime Gateway、微信 / 飞书 OAuth Callback、Webhook、邮件、Provider Adapter、Secret、Timeout / Retry / Circuit Breaker 与外部服务失败隔离。

21. `21-Security-Privacy-Threat-Model-Design.md`  
    定义系统整体 Threat Model、租户隔离、Session / Permission 安全、XSS / CSRF / SSRF、文件与 Import 安全、Prompt Injection、Secret、隐私、日志脱敏、安全测试与事故响应。

22. `22-Client-Server-Interaction-Feedback-Flow-Design.md`  
    定义 Query / Command / Async Task / Realtime / Offline 的完整前后端信息流、状态机、反馈语义、Conflict、Partial Failure、Permission 与 Session 状态传播。

23. `23-Application-Logging-Diagnostics-Design.md`  
    定义应用日志、Client Telemetry、Trace、requestId / traceId / eventId / taskId 关联、错误目录、敏感信息脱敏与跨服务排障链路。

24. `24-Testing-Quality-Release-Design.md`  
    定义 Unit / Contract / Integration / Realtime / Offline / Security / Load / Migration 测试、Release Gate、Canary、Rollback 与长期回归策略。

25. `25-Async-Task-Execution-Design.md`  
    定义统一 Async Task Runtime，包括 Task / Attempt / Lease / Fencing / Retry / Cancel / Progress / Priority / Worker Pool / Dead Letter / Reconciliation。

26. `26-Technology-Stack-Decision.md`  
    正式锁定 React/Vite、FastAPI、WebSocket/Yjs Realtime、PostgreSQL、NATS JetStream、Valkey、OpenSearch、S3、Observability、Testing、Build 与 Production Deployment 技术栈。

27. `27-Repository-Module-Layout-Design.md`  
    正式锁定 Monorepo 目录、Frontend Feature、Python Domain/Application/Infrastructure、Realtime、Worker、Contract、Migration 与依赖方向。

28. `28-Contract-Schema-Registry-Design.md`  
    将 Command / Query / Event / Stream / Task / Error 转为 JSON Schema + OpenAPI 驱动的机器可读 Contract Registry，并生成 TypeScript / Python Contract。

29. `29-PostgreSQL-Logical-Data-Model-Design.md`  
    定义 PostgreSQL 的 auth/core/collab/work/integration/audit 逻辑模型、实体关系、约束、Outbox/Inbox、Task、Journal、Checkpoint 与事务边界。

## Canonical Owner 关系

```text
Architecture Constitution
│
├── Content Model
│   ├── 03 Resource Collaboration
│   └── 01 Block / Node
│       └── 02 Node Identity
│
├── Communication
│   ├── 04 Unified Module Communication
│   ├── 05 Realtime Protocol
│   ├── 18 Client Runtime / Integration
│   ├── 19 Frontend Module Contracts
│   └── 22 Interaction / Feedback Semantics
│
├── Core Backend
│   ├── 06 Persistence
│   ├── 07 Permission
│   ├── 08 History
│   ├── 09 Lifecycle
│   ├── 10 Asset
│   ├── 11 Search
│   ├── 12 AI / ChangeSet
│   ├── 13 Import / Export
│   ├── 16 Auth / Session
│   └── 17 Comment / Mention / Notification
│
└── Production Platform
    ├── 14 Observability / Operations
    ├── 15 Deployment / Scaling / DR
    ├── 20 Gateway / External Integration
    ├── 21 Security / Privacy
    ├── 23 Logging / Diagnostics
    ├── 24 Testing / Quality / Release
    ├── 25 Async Task Execution
    ├── 26 Technology Stack
    ├── 27 Repository / Module Layout
    ├── 28 Contract Schema Registry
    └── 29 PostgreSQL Logical Data Model
```

### Conflict Resolution

```text
Architecture Constitution
> Canonical Owner
> Specialized Subordinate Design
> Example / Recommendation
```

`PRODUCT_DECISION_PENDING` 仅用于未来尚未确认的产品行为；当前 01-29 已列出的产品决策均已收口。

后续新增设计文档继续沿用编号和简短英文文件名，不再使用临时或含空格的混乱命名。
