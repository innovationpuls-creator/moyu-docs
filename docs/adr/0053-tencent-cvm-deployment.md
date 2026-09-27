# ADR 0053: 腾讯云 Ubuntu 单机部署路径

状态：Proposed，等待用户确认。

## Context

用户指定最终目标为腾讯云 Ubuntu Server 24.04 LTS 64-bit。项目当前架构文件 `docs/architecture/26-Technology-Stack-Decision.md` 冻结 Production 为 Kubernetes + Helm + Terraform；本仓库新增的 `compose.yaml` 是本地开发栈，包含本地 PostgreSQL 和 MinIO，并把 Web 绑定到回环地址。直接在单台 CVM 上使用 Compose 会改变生产部署方案，也会保留 CVM、NATS 和 Valkey 的单点故障。

二进制资产需要独立对象存储。腾讯 COS 提供 S3 兼容 API，但新建 Bucket 不支持 path-style 域名；Asset Store 需要使用 virtual-hosted-style。代码现已增加可配置寻址方式，本地 MinIO 默认继续使用 path-style。

## Decision

建议将“单 CVM + Docker Compose + 腾讯 COS + 腾讯云 PostgreSQL 高可用实例”作为第一阶段部署路径，前提是用户接受单 CVM、NATS 和 Valkey 的单点故障，以及本阶段偏离现有 Production Kubernetes 约束。服务器专用 Compose、TLS 入口和生产密钥配置待确认后再实现。

如果部署必须满足高可用与横向扩展要求，则保留 Kubernetes + Helm + Terraform 路径；单台 CVM 不能满足该目标。

## Alternatives

1. **Kubernetes + Helm + Terraform**：符合现有生产架构，支持多实例和滚动发布；需要集群与额外云资源，不是单服务器方案。
2. **单 CVM + Docker Compose**：直接使用指定 Ubuntu 主机，实施成本低；应用入口、NATS 和 Valkey 仍是单点，需批准作为阶段性例外。
3. **单 CVM + 单节点 Kubernetes**：保留 Kubernetes API，但单节点仍然是可用性单点，并增加集群运维复杂度，当前没有证据表明它比 Compose 更适合此目标。

## Consequences

- 本地开发继续使用 Docker Compose 与 MinIO。
- 腾讯云第一阶段的 Asset 数据使用私有 COS Bucket；PostgreSQL 使用托管高可用实例，避免业务数据和文件依赖单台主机磁盘。
- 单 CVM 路径仍需补齐 NATS/Valkey 的持久化、TLS、日志轮转、镜像更新和备份恢复方案；不能宣称具备应用层高可用。
- 迁移到多节点生产环境时，应转为 Kubernetes + Helm，并保留 COS 与 PostgreSQL 的托管服务边界。

## Migration

用户确认单机路径后，新增服务器专用 Compose 配置与非 README 部署手册；配置外部 PostgreSQL、COS `virtual` 寻址、独立生产密钥、TLS 入口和资源限制。先在本地按服务器配置构建并做健康检查，再连接用户指定的 CVM 部署。

若用户要求高可用，则不新增服务器 Compose；改按 Kubernetes + Helm + Terraform 做部署计划，并确认 TKE 或自管集群及 Ubuntu 节点镜像要求。

## Rollback

单机部署使用固定镜像版本并保留前一版本，以便回滚应用镜像。数据库迁移必须保持兼容并先备份；回滚时恢复先前镜像与已验证的数据库备份。COS 对象不随应用回滚删除。部署前先在无生产数据环境验证迁移和恢复步骤。
