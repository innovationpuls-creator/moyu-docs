# 腾讯云 Ubuntu Server 24.04 部署

状态：DOM 的单机 Compose 已改为本机 PostgreSQL 与 MinIO；公网域名和 TLS 路由接入 OneTree 后，站点可对外开放。

## 部署方案

DOM 使用独立 Docker Compose 项目，启动 PostgreSQL 18、MinIO、NATS、Valkey、API、Realtime、Worker 和 Web。PostgreSQL、MinIO 与 NATS 使用持久卷；Valkey 是可重建缓存。

数据库和对象存储不发布宿主机端口。MinIO 创建私有 dom-assets bucket，只供 DOM 容器访问。DOM 使用自己的 PostgreSQL、MinIO 和数据卷，不读取或改动 OneTree 的数据库和文件。

OneTree 已占用宿主机 80/443。DOM 的 Web 容器加入现有 deploy_default 网络并使用 dom-web 别名；OneTree Nginx 负责域名路由与 HTTPS，现有 Certbot 负责证书签发和续期。DOM 不另起 Caddy，不抢 OneTree 的端口。

## 域名和证书

证书需要一个指向这台 CVM 公网 IP 的域名 A 记录，且 TCP 80/443 从公网可达。证书通过 OneTree 现有 Nginx 与 Certbot 流程签发和续期。当前需要确定 DOM 使用的具体域名，才能添加 Nginx 路由并申请证书。

## 准备部署包

提交部署代码后，在本机仓库运行 scripts/package-tencent-cvm.sh。脚本自动生成 PostgreSQL、MinIO 和应用密钥，将环境文件权限设为仅当前用户可读写，并生成部署压缩包。部署包内会把服务器 Compose 配置复制为默认 compose.yaml，因此服务器不需要编辑环境文件或输入 Git、Python、Node 命令。

将压缩包上传并解压到服务器 /opt/dom。

## 启动命令

在 /opt/dom 目录中只需要运行：

    docker compose up -d --build

Compose 会构建应用、启动本机数据库和对象存储、创建 MinIO 私有 Bucket、运行数据库迁移，再启动网站服务。以后更新部署包后仍运行同一条命令。

查看容器状态可运行 docker compose ps；查看日志可运行 docker compose logs -f。停止服务可运行 docker compose down；不要添加 -v，否则会删除 DOM 数据卷。

## 邮件与数据恢复

普通注册会直接激活账号，不需要邮箱验证，也不需要 SMTP。密码找回等发邮件功能只有在提供 SMTP 配置后才能使用；它们不影响站点启动或正常注册。

PostgreSQL、MinIO 和 NATS 数据都在这台 CVM 的 Docker 卷中。服务器故障或磁盘损坏可能同时影响这些数据；应将备份保存到服务器之外。当前 Compose 配置没有自动异地备份，也不构成高可用部署。
