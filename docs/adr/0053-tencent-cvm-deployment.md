# ADR 0053: 腾讯云 Ubuntu 单机部署路径

状态：Superseded for the existing Tencent CVM by ADR 0054; retained as history.

## Context

用户指定最终目标为腾讯云 Ubuntu Server 24.04 LTS 64-bit，并明确要求服务器侧部署与日常操作通过 Docker 命令完成。项目架构文件 `docs/architecture/26-Technology-Stack-Decision.md` 的高可用生产目标为 Kubernetes + Helm + Terraform；本仓库 `compose.yaml` 是本地开发栈，包含本地 PostgreSQL 和 MinIO，并把 Web 绑定到回环地址。单台 CVM 的 Compose 部署保留应用主机、NATS 和 Valkey 的单点故障，因此作为受范围约束的第一阶段部署例外，不宣称达到多实例高可用基线。

二进制资产需要独立对象存储。腾讯 COS 提供 S3 兼容 API，但新建 Bucket 不支持 path-style 域名；Asset Store 需要使用 virtual-hosted-style。代码现已增加可配置寻址方式，本地 MinIO 默认继续使用 path-style。

## Decision

第一阶段采用“单 CVM + Docker Compose + Caddy + 腾讯 COS + 腾讯云 PostgreSQL 高可用实例”。服务器专用 Compose 自动运行数据库迁移；Caddy 提供 HTTPS/WSS；COS 使用 virtual-hosted-style；只有 Caddy 发布公网 80/443 端口。NATS JetStream 数据使用命名卷持久化，Valkey 仅作可重建缓存。生产环境通过部署目录中预先准备的环境文件注入凭据，环境文件不进入 Git。

该路径的应用入口、NATS 和 Valkey 在单 CVM 故障期间不可用，不能满足多实例应用高可用目标。正式多实例高可用部署仍使用 Kubernetes + Helm + Terraform；达到该目标时迁移应用编排，继续使用 COS 与托管 PostgreSQL。

## Alternatives

1. **Kubernetes + Helm + Terraform**：符合现有生产架构，支持多实例和滚动发布；需要集群与额外云资源，不是单服务器方案。
2. **单 CVM + Docker Compose**：直接使用指定 Ubuntu 主机，实施成本低；应用入口、NATS 和 Valkey 仍是单点，需批准作为阶段性例外。
3. **单 CVM + 单节点 Kubernetes**：保留 Kubernetes API，但单节点仍然是可用性单点，并增加集群运维复杂度，当前没有证据表明它比 Compose 更适合此目标。

## Consequences

- 本地开发继续使用 Docker Compose 与 MinIO。
- 腾讯云第一阶段的 Asset 数据使用私有 COS Bucket；PostgreSQL 使用托管高可用实例，避免业务数据和文件依赖单台主机磁盘。
- NATS 数据写入命名卷；Valkey 是不持久化的可重建缓存。CVM 持久卷的备份与恢复仍需纳入主机备份计划；该部署不能宣称具备应用层高可用。
- Caddy 持有自动签发 TLS 证书所需的数据卷；正常停止或更新使用 `docker compose down`，不删除命名卷。
- 迁移到多节点高可用生产环境时，应转为 Kubernetes + Helm，并保留 COS 与 PostgreSQL 的托管服务边界。

## Migration

服务器专用 Compose、Caddyfile、环境文件模板和非 README 部署手册已纳入仓库。先在本地验证 Compose 解析与镜像构建；真正连接 CVM 前，用户需准备公网域名、腾讯云资源和服务器环境文件。部署会由服务器侧 Docker Compose 执行，不包含本 ADR 对实际腾讯云资源的变更授权。

若后续要求应用层高可用，则按 Kubernetes + Helm + Terraform 做多实例部署，并确认 TKE 或自管集群及节点镜像要求。

## Rollback

单机部署使用固定镜像版本并保留前一版本，以便回滚应用镜像。数据库迁移必须保持兼容并先备份；回滚时恢复先前镜像与已验证的数据库备份。COS 对象不随应用回滚删除。部署前先在无生产数据环境验证迁移和恢复步骤。
