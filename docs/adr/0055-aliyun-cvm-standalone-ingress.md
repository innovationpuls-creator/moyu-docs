# ADR 0055: 阿里云单机以独立入口部署墨屿

状态：Accepted。

适用范围：用户指定的阿里云 Ubuntu Server 24.04 CVM，公网 IPv4 `8.162.7.16`。本决策用于当前墨屿部署；腾讯云上的 OneTree 保持独立运行。

## Context

当前腾讯云主机运行 OneTree，OneTree Nginx 已处理该主机的公网 80/443，并曾将该 IP 的默认 HTTPS 流量转发到墨屿。这会让直接访问该 IP 时显示 OneTree 或依赖共享路由。用户指定把墨屿迁至阿里云，并要求不引入 DNS 依赖。阿里云主机为 Ubuntu 24.04，公网 IPv4 为 `8.162.7.16`，当前 80/443 未监听，Docker 尚未安装；其 PostgreSQL、MinIO 与应用由独立 Compose 运行。

## Decision

- 在阿里云单独运行 PostgreSQL 18、MinIO、NATS、Valkey、API、Realtime、Worker、Web、Nginx 与 Certbot；所有状态使用独立 Docker named volumes。
- 阿里云 Nginx 独占本机 80/443，HTTP-01 webroot 为短期 IP 证书提供验证，HTTPS 转发到墨屿 Web。Certbot 使用 `shortlived` profile，每 6 小时检查续期并在更新后 reload Nginx。
- 部署包生成该主机自己的密钥和 Compose 配置；数据库和存储端口不发布到公网。启动与更新使用 Docker Compose。
- 迁移时先导出腾讯云墨屿的 PostgreSQL 和 MinIO 数据，并在阿里云恢复、验证后切流。腾讯云 OneTree 保持运行，墨屿旧容器与路由在新站验收后单独移除；不删除 OneTree 容器、配置、网络、卷或域名。

## Alternatives

1. 继续使用腾讯云 OneTree ingress：已经出现 IP 默认路由回落 OneTree 的情况，且墨屿生命周期和 OneTree 入口共享配置。
2. 在新机器绑定域名：用户只授权使用已购 `onetree.chat`，该域名服务 OneTree；将其指向墨屿会更改既有产品域名归属。
3. 使用自签名证书：浏览器不能默认信任，无法提供正常 HTTPS 访问体验。

## Consequences

- 用户通过 `https://8.162.7.16` 访问墨屿，不需要新购或配置域名。
- Let’s Encrypt IP 证书属于短有效期证书，必须持续运行自动续期容器，并允许公网 TCP 80/443 入站。
- 阿里云成为墨屿的独立入口；OneTree 的 DNS、TLS、容器和路由无需改动。
- PostgreSQL、MinIO、NATS 和应用仍共享单机故障域，需安排异机备份。

## Migration

先在阿里云安装 Docker，上传部署包和腾讯云导出的数据；导入数据库与对象数据，启动服务，确认 HTTPS、登录、文档和附件访问正常。验收后再停止腾讯云墨屿 Compose 项目并移除其 IP 路由，保留旧数据卷作为回退快照，直到用户确认不再需要。

## Rollback

若阿里云验收失败，保留腾讯云 OneTree 和墨屿数据卷不动，可恢复腾讯云墨屿 Compose 与专属 Nginx 路由。回退前后不得对 `deploy_*` OneTree 卷执行清理。
