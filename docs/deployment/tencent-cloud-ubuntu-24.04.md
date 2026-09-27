# 腾讯云 Ubuntu Server 24.04 单机部署

状态：服务器 Compose 与部署包脚本已准备；还没有真实 COS、PostgreSQL、域名或凭据，因此没有连接腾讯云资源。

## 已选方案

目标主机是腾讯云 Ubuntu Server 24.04 LTS 64-bit。Web、API、Realtime、维护 Worker、NATS、Valkey 和 Caddy 由独立的 `compose.server.yaml` 运行。文件资产存入私有 COS，业务数据库使用腾讯云 PostgreSQL 高可用实例。Caddy 负责 HTTPS/WSS 和证书续期。

该单机方案满足服务器端以 Docker Compose 管理应用的要求。CVM、应用入口、NATS 和 Valkey 仍是单点；CVM 故障期间应用与实时协作不可用。托管 PostgreSQL 与 COS 可减少数据库和文件对主机磁盘的依赖，但不会让应用主机变成高可用。多实例高可用部署仍按 Kubernetes + Helm + Terraform 路径执行；决策记录见 `docs/adr/0053-tencent-cvm-deployment.md`。

本地 `compose.yaml` 继续使用 PostgreSQL 和 MinIO，不作为服务器文件。服务器 Compose 只发布 Caddy 的 TCP 80/443；PostgreSQL、NATS、Valkey 和 Web 不发布公网端口。NATS 使用命名卷，Valkey 作为可重建缓存且不做持久化。容器日志配置为每个文件最多 10 MB、保留 3 个文件。

## 腾讯云资源

| 资源 | 配置要求 |
| --- | --- |
| CVM | Ubuntu Server 24.04 LTS 64-bit；Docker Engine 与 Compose 插件已安装；CVM 与 PostgreSQL、COS 尽量同地域 |
| 安全组 | 公网开放 TCP 80/443；SSH 仅开放给管理端来源；不要开放数据库、NATS、Valkey 或应用内部端口 |
| DNS | 将应用域名的 A 记录指向 CVM 公网 IP；如果没有配置 IPv6，不要发布错误的 AAAA 记录 |
| TLS | Caddy 通过公网域名自动签发和续期证书；证书签发要求 DNS 指向该 CVM，外网可访问 TCP 80/443 |
| PostgreSQL | 选择高可用实例；建独立数据库和应用账号；配置 VPC 网络与 SSL；数据库安全组只允许应用 CVM 访问 |
| COS | 建立私有 Bucket；创建仅能访问目标 Bucket 的 CAM 凭据；环境变量使用 COS `virtual` 寻址 |
| 邮件 | 提供支持 SMTP + STARTTLS 的邮件账号，用于邀请与账号邮件 |

## 本地准备部署包

在本地仓库将 `deploy/tencent-cvm/server.env.example` 复制为 `deploy/tencent-cvm/server.env`，填写真实域名、PostgreSQL、COS 和 SMTP 参数。数据库连接串中的保留字符必须 URL 编码。两个加密密钥分别使用 `openssl rand -base64 32` 生成。`server.env` 已加入 `.gitignore`；不要把真实凭据提交到 Git。

执行 `scripts/package-tencent-cvm.sh`。首次执行会创建环境文件模板并退出；填写完成后再次执行，会在 `dist/` 生成包含源码和环境文件的压缩部署包。部署包在本地设置为仅当前用户读写。将压缩包在本地解压，再通过文件传输工具把目录内容上传到服务器 `/opt/dom`；服务器上不需要输入解压、Git 或 Node/Python 构建命令。

## 服务器部署命令

前提是 Docker Engine / Compose 已安装，部署包已解压到 `/opt/dom`，`server.env` 中所有值有效，域名与安全组也已配置。随后服务器上只需运行这一条 Docker 命令：

```sh
docker compose --project-directory /opt/dom --env-file /opt/dom/deploy/tencent-cvm/server.env -f /opt/dom/compose.server.yaml up -d --build
```

Compose 会构建固定基础镜像上的应用镜像，等待 PostgreSQL 迁移完成，再启动 API、Realtime、Worker、Web 与 Caddy。Caddy 在域名和端口条件满足时自动申请证书。更新仍运行同一条命令；查看状态和日志、停止服务也使用同一组 `docker compose` 选项。停止时执行 `down`，不要加 `-v`，以保留 Caddy 证书与 NATS 数据卷。

## 未验证项

目前尚未使用真实腾讯云 PostgreSQL、COS Bucket、SMTP 或公网域名做端到端部署验证。Compose 配置与应用镜像构建可在本地验证；实际首次部署仍依赖这些资源的网络规则和凭据正确。

参考：[Docker Engine Ubuntu 安装文档](https://docs.docker.com/engine/install/ubuntu/)、[Docker Compose Linux 安装文档](https://docs.docker.com/compose/install/linux/)、[Caddy 自动 HTTPS](https://caddyserver.com/docs/automatic-https)、[腾讯云 COS S3 兼容配置](https://intl.cloud.tencent.com/document/product/436/34688?lang=en)、[COS 域名寻址说明](https://cloud.tencent.com/document/product/436/102489)、[腾讯云 PostgreSQL 高可用与版本说明](https://cloud.tencent.com/document/product/409/7562)。
