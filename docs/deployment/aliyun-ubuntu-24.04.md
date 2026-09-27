# 阿里云 Ubuntu 24.04 单机部署

本部署包适用于独立阿里云 CVM，不依赖腾讯云 OneTree 的 Nginx、Docker 网络、数据库、对象存储或证书卷。应用、PostgreSQL、MinIO、NATS、Valkey、入口 Nginx 和 Certbot 由同一份 Docker Compose 管理。

公网入口使用服务器 IPv4。Certbot 每 6 小时检查续期，申请失败时继续重试。IP 证书有效期约 160 小时，因此应保持 Compose 中的 `certbot` 服务运行。

## 准备包

在开发机运行：

```sh
scripts/package-aliyun-cvm.sh 8.162.7.16
```

把生成的 `dist/aliyun-cvm-deploy-*.tar.gz` 上传到服务器并解压到 `/opt/moyu`。解压后先运行 `deploy/aliyun-cvm/initialize-env.sh 8.162.7.16`，在服务器本机生成数据库、MinIO 和应用密钥；密钥不会放入部署归档。

## 启动

在 `/opt/moyu` 执行：

```sh
docker compose --parallel 1 up -d --build
```

首次启动会构建应用镜像并运行 PostgreSQL schema migration。IP 证书签发后，HTTP 自动跳转到 HTTPS。注册账户默认即可使用系统；未配置 SMTP 时不发送邮件。

## 日常检查与更新

```sh
docker compose ps
docker compose logs -f --tail=100
```

更新部署包后再次执行 `docker compose --parallel 1 up -d --build`。不要执行带 `-v` 的 `down`，以免删除数据库、MinIO、NATS 或证书卷。

当前部署是单机方案。应用和持久数据共同依赖这台 CVM；生产数据仍需定期备份到主机之外。
