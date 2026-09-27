# ADR 0054: 腾讯云单机使用本机 PostgreSQL 与 MinIO

状态：Accepted。

适用范围：用户现有的腾讯云 Ubuntu Server 24.04 CVM；本决策针对这台已运行 OneTree 的主机，并取代 ADR 0053 对该主机的部署选择。

## Context

用户已确认希望使用与 OneTree 相似的本机 PostgreSQL 和 Docker 对象存储方案，并要求 DOM 与 OneTree 不冲突。现有 DOM 本地 Compose 已使用 PostgreSQL 18、MinIO 和持久卷；业务代码通过 PostgreSQL 与 S3-compatible Object Storage 接口访问数据。单机环境中 OneTree 已持有宿主机 80/443 端口，并运行 Nginx 与 Certbot。

## Decision

- DOM 作为独立 Compose 项目运行，使用独立 PostgreSQL 18、MinIO、NATS、Valkey 和应用容器。
- PostgreSQL 和 MinIO 各自使用 DOM 专属 Docker volume；MinIO 创建私有 dom-assets bucket。
- PostgreSQL、MinIO、NATS、Valkey、API、Realtime、Worker 和 Web 不发布宿主机端口。只有 DOM Web 加入 OneTree 的 deploy_default 网络，并以 dom-web 作为网络别名。
- OneTree 现有 Nginx 继续处理 DOM HTTP、HTTPS 和 WebSocket 流量；现有 Certbot webroot 与证书续期服务负责域名证书。DOM 不启动第二个公网 Edge，也不绑定 80/443。
- 部署包生成 PostgreSQL、MinIO 和应用密钥，并放入权限受限的忽略文件。正常注册直接激活，不要求 SMTP；需要邮件的功能仅在提供 SMTP 配置后可用。

## Alternatives

1. 使用托管 PostgreSQL 与 COS：数据库和对象可独立于 CVM，但需要额外云资源、凭据与网络配置，与用户确认的本机方案不符。
2. 为 DOM 再启动 Caddy：与 OneTree 已占用的 80/443 冲突，并重复承担 TLS 入口。
3. 复用 OneTree 的 PostgreSQL 容器或数据卷：减少容器数量，但会让 DOM 数据与 OneTree 生命周期、权限和恢复过程耦合，因此不采用。

## Consequences

- 用户无需开通腾讯云 PostgreSQL 或 COS，也无需为正常注册配置邮件服务。
- DOM 数据与 OneTree 数据完全隔离，但 DOM 的数据库与对象文件仍共同依赖该 CVM。主机故障或磁盘损坏可能同时影响应用、数据库和文件。
- PostgreSQL、MinIO 与 NATS 卷必须纳入主机以外的备份和恢复计划。当前部署方案不宣称具备高可用或异地备份。
- 恢复 OneTree Nginx 配置时，DOM 的域名路由也必须保留；Certbot 证书存储沿用 OneTree 的现有卷。

## Migration

部署脚本生成本机数据服务凭据，并将服务器 Compose 文件打包为默认 Compose 文件。部署目录到位后，服务器运行一条 Docker Compose 命令即可启动并自动执行数据库迁移。

若已有 DOM 托管数据库或 COS 数据，切换前必须导出并导入 PostgreSQL 与对象数据；本 ADR 不授权删除旧数据。当前目标主机尚未运行 DOM，因此首次启动从空的 DOM 专属卷开始。

## Rollback

使用 Docker Compose 停止或回退应用时保留命名卷，不执行删除卷的命令。若迁移结果不兼容，应恢复备份后再启动旧版应用。切回托管服务前，先从本机 PostgreSQL 与 MinIO 导出并验证数据。
