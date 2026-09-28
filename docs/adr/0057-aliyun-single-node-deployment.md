# ADR-0057: 阿里云 Ubuntu 24.04 单机 Docker Compose 部署

## Status

Accepted

## Context

ADR 0056 已解除 `docs/architecture/26` 对生产平台的锁定（Kubernetes + Helm → 由 docker skills 按项目目标在部署时决策）。本次任务为项目选定第一个生产部署形态：部署到阿里云 ECS（Ubuntu 24.04）。

现状约束：

- 目标是单台 ECS + 一个公网 IPv4（无备案域名）；入口需要 HTTPS（邮件链接、Secure Cookie、现代浏览器告警都要求）。
- 技术栈已冻结（`docs/architecture/26`）：PostgreSQL 18、Valkey 9、NATS JetStream、S3 兼容对象存储、Node 24 / Python 3.12、Alembic 迁移；阶段一物理架构为 Modular Monolith API + Realtime + Worker（`26 §2`）。
- 仓库此前不存在任何 Docker 产物；多实例高可用仍是生产硬性目标（`26` 硬约束 14），但不应让第一阶段部署背上集群平台的完整复杂度。

## Decision

第一阶段生产形态 = **单机 Docker Compose + 自托管基础设施 + Let's Encrypt 短期 IP 证书**：

- **编排**：根目录 `compose.yaml`，服务：postgres / valkey / nats / minio(+init) / migrate / api / realtime / maintenance-worker / web / gateway / certbot。
- **应用镜像**：每服务独立多阶段 Dockerfile（`services/api` `services/realtime` `workers/maintenance` `apps/web`），非 root 运行、健康检查、日志轮转；依赖安装源可经构建参数覆盖（`UV_IMAGE` / `PYPI_INDEX_URL` / `NPM_REGISTRY`），兼顾国内网络的镜像加速。
- **入口**：`gateway`（nginx）终止 TLS、HTTP→HTTPS、承载 ACME 验证路径；`web` 容器 nginx 做 SPA + 同源反代（`/v1` 与 WebSocket），浏览器零 CORS。公网只发布 80/443。
- **证书**：无域名场景使用 Let's Encrypt **IP 地址证书**（RFC 8738，`--preferred-profile shortlived`，约 6 天有效期），`certbot` 容器每 6 小时签发/续期循环；gateway 先以 HTTP bootstrap 服务 ACME，证书就绪后 reload 为 HTTPS。
- **对象存储**：自托管 MinIO（`dom-assets` 桶）；业务侧只依赖统一 `S3_ASSET_*` 环境变量接口，可平替阿里云 OSS。MinIO 官方 Docker 镜像自 2025-10 停止免费分发（Docker Hub 仓库已删除），采用 Chainguard 构建的 `cgr.dev/chainguard/minio` 镜像（digest 固定），S3 行为与官方一致；distroless 运行时健康检查用 sidecar（`minio-health`，`curlimages/curl` 共享网络命名空间）。
- **密钥**：`initialize-env.sh` 在服务器本地生成 `.env`（mode 600，不入仓库），compose 全部敏感值经 `${VAR:?}` 强制注入。
- **迁移**：一次性 `migrate` 服务运行 Alembic `upgrade head`（唯一迁移入口，`26 §25`），幂等可重跑。
- **备份**：`backup.sh`（pg_dump + gzip，保留 7 天）+ MinIO 每日快照命令，文档强调备份必须同步到主机之外。

## Alternatives

- **托管 PostgreSQL（阿里云 RDS）+ 对象存储 OSS**：运维省心、天然多副本，但引入 AccessKey/费用与网络依赖；当前阶段保留环境变量接口，后续可无代码切换（ADR 0056 的多实例目标路径之一）。未在本阶段强制。
- **Kubernetes（ACK / 自建）**：符合多实例目标，但单 ECS、单公网 IP 场景下集群控制面与 Ingress 成本远超收益。拒绝。
- **仅 HTTP（不配证书）**：Secure Cookie、邮件链接、浏览器安全提示均受影响。拒绝。
- **标准域名证书**：需要 ICP 备案 + 域名，当前无备案域名；方案保留（改 `MAIL_LINK_BASE_URL` 与 gateway 模板 `server_name` 即可）。
- **参考历史部署产物**：仓库曾存在旧版 Aliyun 部署包，已按 ADR 0056 移除且被判定为有问题的版本；本方案按 docker skills 规格从零编写，不复用。

## Consequences

- **正面**：一条命令部署（`docker compose --parallel 1 up -d --build`）；零云产品依赖、成本低；镜像规范符合 `26 §55`（OCI/多阶段/非 root）；依赖顺序由健康检查与完成条件保证；单机内实时协同、任务队列、附件存储完整可用；IP 证书解决无域名 HTTPS。
- **负面 / 风险**：
  1. **单点**：ECS 故障 = 服务中断；数据卷丢 = 数据全失。必须外置备份，文档明确。
  2. **IP 证书**：有效期约 6 天，依赖常驻续期与 80 端口公网可达；极老客户端可能不信任 IP 证书。
  3. 单机性能上限；多实例高可用目标仍待后续（ACR + 多机 / K8s）达成，本 ADR 保留演进路径。
  4. 国内网络拉取 Docker Hub / ghcr 镜像可能缓慢，需要加速器或镜像源覆盖（文档 §2、§4.3）。

## Migration

1. 落库本 ADR（0057）。
2. 根目录新增 `compose.yaml`、`.dockerignore`；各服务新增 `Dockerfile`（api / realtime / maintenance-worker / web）。
3. `scripts/deploy-aliyun/` 新增初始化、入口、证书、备份、打包脚本；`apps/web/nginx.conf` 为 web 容器反代配置。
4. `docs/runbooks/aliyun-ubuntu-24.04.md` 落库部署手册（前置、步骤、运维、备份恢复、回滚、FAQ）。
5. 手工验证：`docker compose config`、四镜像构建、本机 compose 冒烟（见提交说明）。

## Rollback

删除根目录 `compose.yaml`、`.dockerignore`、各服务 `Dockerfile`、`apps/web/nginx.conf`、`scripts/deploy-aliyun/`，并回退部署手册与本 ADR；不涉及运行时数据或 Schema，仅文档与构建产物状态。服务器上已生成的数据卷不受影响（`docker compose down` 不带 `-v`）。