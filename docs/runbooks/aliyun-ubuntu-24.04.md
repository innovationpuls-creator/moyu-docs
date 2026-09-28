# 阿里云 Ubuntu 24.04 单机部署手册（墨屿）

> 部署形态决策见 `docs/adr/0057-aliyun-single-node-deployment.md`。
> 编排文件：根目录 `compose.yaml` + `scripts/deploy-aliyun/`；镜像定义见各服务 `Dockerfile`。

## 1. 部署拓扑

单台 ECS 上由 Docker Compose 管理全部组件：

```text
公网 80/443
   │
   ▼
gateway (nginx:stable-alpine)   ← TLS 终止、HTTP→HTTPS、ACME 验证路径
   │
   ▼
web (nginx-unprivileged)        ← 静态 SPA + 同源反代 /v1 与 WebSocket
   ├── api (FastAPI, uvicorn)         → PostgreSQL 18 / NATS / Valkey / MinIO
   └── realtime (TS WebSocket + Yjs)  → PostgreSQL（collab schema）/ NATS / Valkey
maintenance-worker (Python daemon)    → PostgreSQL / NATS / MinIO
certbot (Let's Encrypt 短期 IP 证书)  → 每 6 小时签发/续期
```

- 对外只发布 80/443；PostgreSQL / Valkey / NATS / MinIO 只在 Compose 内网可达。
- 邮件默认 `MAILER_PROVIDER=logging`（验证码写 API 日志，开箱即用）；配 SMTP 后走真实邮件。
- 附件存储在自托管 MinIO（`dom-assets` 桶），环境变量接口与阿里云 OSS 兼容。
  MinIO 官方 Docker 镜像自 2025-10 起停止免费分发、Docker Hub 仓库已删除（参见 [gigazine 报道](https://gigazine.net/gsc_news/en/20251023-minio-stops-distributing-free-docker-images) 与 [Chainguard 替代方案](https://www.chainguard.dev/unchained/secure-and-free-minio-chainguard-containers)）；本部署使用 Chainguard 基于官方源码构建的 `cgr.dev/chainguard/minio` 镜像（digest 固定），S3 行为与官方一致。

## 2. 前置条件（一次性）

1. **ECS**：Ubuntu 24.04，建议 2 vCPU / 4 GiB 起、系统盘 40 GiB 以上（镜像构建与 pg 数据都需要空间）。
2. **公网 IP**：短期 IP 证书需要；`MAIL_LINK_BASE_URL` 与邮件链接也基于它。
3. **安全组放行**：入方向至少 `80/tcp`、`443/tcp`、`22/tcp`（SSH）。**80 必须对公网开放**——Let's Encrypt 通过 HTTP-01 验证 IP 归属，80 不可达则证书永远签不下来。
4. **Docker Engine + Compose 插件**：

   ```sh
   curl -fsSL https://get.docker.com | sh
   systemctl enable --now docker
   docker compose version   # 需要 v2 及以上
   ```

5. **国内网络拉镜像**（Docker Hub / ghcr.io 连通性差时的加速，任选其一）：
   - 推荐：阿里云容器镜像服务提供的**个人加速器地址**（`https://<你的加速地址>.mirror.aliyuncs.com`），写入 `/etc/docker/daemon.json` 后 `systemctl restart docker`：

     ```json
     { "registry-mirrors": ["https://<你的加速地址>.mirror.aliyuncs.com"] }
     ```
   - 依赖安装（npm / PyPI）可在 `.env` 里覆盖（见 §4.3）。
   - 若 ghcr.io 的 UV 构建镜像拉不动，可在 `.env` 设 `UV_IMAGE=<代理地址>/astral-sh/uv:python3.12-bookworm-slim`（如公网代理镜像站），或改 `services/api/Dockerfile` 首行 ARG 默认值。

## 3. 源码上机

三种方式任选：

- **rsync**（有 SSH）：`rsync -a --exclude .git --exclude node_modules --exclude .venv ./ root@<SERVER>:/opt/moyu/`
- **打部署包**（开发机）：
  ```sh
  scripts/deploy-aliyun/package.sh
  scp dist/deploy/dom-deploy-<时间戳>.tar.gz root@<SERVER>:/opt/
  ssh root@<SERVER> 'mkdir -p /opt/moyu && tar xzf /opt/dom-deploy-<时间戳>.tar.gz -C /opt/moyu'
  ```
- **git clone**：`git clone <仓库> /opt/moyu`（服务器需要仓库访问权限）。

后续所有命令都在 `/opt/moyu`（compose.yaml 所在目录）执行。

## 4. 首次启动

### 4.1 生成服务器本地密钥

```sh
cd /opt/moyu
scripts/deploy-aliyun/initialize-env.sh <公网IPv4>
```

生成 `.env`（mode 600）：POSTGRES 密码、MinIO 管理员口令、两个幂等加密密钥、`MAIL_LINK_BASE_URL=https://<IP>`。**密钥只存在于服务器**，不入仓库。重复执行会被拒绝（防止误覆盖）。

### 4.2 构建并启动

```sh
docker compose --parallel 1 up -d --build
```

- `--parallel 1`：同一台低配机器上串行构建，避免内存峰值。
- 首次会构建 4 个应用镜像（api / realtime / maintenance-worker / web），随后按依赖顺序拉起：postgres → migrate（Alembic `upgrade head`）→ valkey/nats/minio → api → realtime → maintenance-worker → web → gateway → certbot。
- migrate / minio-init 是一次性任务，成功后容器保持 exited；`up` 重复执行时会幂等重跑（alembic 幂等、`mc mb --ignore-existing` 幂等）。

### 4.3 可选配置（追加到 /opt/moyu/.env）

```sh
# 国内镜像（构建期依赖安装）
NPM_REGISTRY=https://registry.npmmirror.com
PYPI_INDEX_URL=https://mirrors.aliyun.com/pypi/simple/

# 真实邮件（不改则验证码写入 api 日志）
MAILER_PROVIDER=smtp
SMTP_HOST=smtp.example.com
SMTP_PORT=587
SMTP_USERNAME=...
SMTP_PASSWORD=...
SMTP_FROM=墨屿 <noreply@example.com>

# 非默认域名场景（有备案域名时）的邮件链接与跨域来源
MAIL_LINK_BASE_URL=https://docs.example.com
CORS_ALLOW_ORIGINS=https://docs.example.com
```

改完 `.env` 后重新 `docker compose --parallel 1 up -d --build`（只有受影响的服务会重建）。

### 4.4 验证

```sh
docker compose ps                # 全部 running（migrate/minio-init 除外，可 exited）
docker compose logs -f --tail=50 api   # 观察启动日志
```

- 浏览器打开 `https://<公网IP>`：证书签发前 gateway 返回 503，签发后（几分钟内）自动切换到 HTTPS。
- `curl -k https://<IP>/healthz` → `ok`（API 经 gateway→web→api 链路）。
- 注册 → 邮箱验证码在 `docker compose logs api`（logging 邮件适配器）中。
- 多开两个浏览器标签登录同一账号同时编辑，验证实时协同（WebSocket）。

## 5. 证书说明（短期 IP 证书）

- 入口使用 **Let's Encrypt IP 地址证书**（`--preferred-profile shortlived`），有效期约 6 天。`certbot` 容器每 6 小时续期，失败不退出、自动重试。
- 首次签发前提：**80 端口公网可达**。若长时间停在 503，`docker compose logs certbot` 看原因（多为安全组未放行 80）。
- 兼容性：IP 证书面向受支持客户端（现代浏览器 OK）；极老客户端可能不信任。若遇到，可降级为 HTTP（安全组只开 80 + 改 gateway 模板）或改用备案域名 + 标准证书。
- 证书文件在 `letsencrypt` 卷（`/etc/letsencrypt/live/<IP>/`）；`docker compose down`（不带 `-v`）不会删除。

## 6. 日常运维

```sh
docker compose ps
docker compose logs -f --tail=100           # 全部
docker compose logs -f realtime             # 指定服务
docker compose restart realtime             # 重启单个服务
docker compose top                          # 进程视图
```

### 更新部署

```sh
rsync -a --delete --exclude .git --exclude node_modules --exclude .venv \
      --exclude .env --exclude backups ./ root@<SERVER>:/opt/moyu/
ssh root@<SERVER> 'cd /opt/moyu && docker compose --parallel 1 up -d --build'
```

`up` 只重建有变更的镜像，数据卷全部保留。**不要执行 `docker compose down -v`**（会删除数据库、MinIO、NATS、证书全部数据卷）。

### 备用入口容器（gateway）故障排查

gateway 是公网唯一入口：`docker compose logs gateway start-gateway.sh` 会在证书缺失时轮询等待；内部配置渲染用 `sed` 替换 `__PUBLIC_IP__`。模板在 `scripts/deploy-aliyun/`，容器内以只读挂载到 `/opt/dom/deploy`。

## 7. 备份与恢复

### 备份

- PostgreSQL（业务主数据）：`scripts/deploy-aliyun/backup.sh`，产物在 `./backups/`，保留 7 天。建议 cron 每日一次：
  ```cron
  23 2 * * * cd /opt/moyu && ./scripts/deploy-aliyun/backup.sh >> backups/backup.log 2>&1
  ```
- MinIO（附件）快照（每日全量镜像，覆盖式）：
  ```sh
  cd /opt/moyu
  docker compose run --rm -v "$PWD/backups:/backups" minio-init \
    mirror --overwrite local/dom-assets /backups/minio-dom-assets
  ```
- **必须把 `backups/` 同步到主机之外**（rsync 到另一台机器 / 阿里云 OSS / NAS）。单机部署下，服务器磁盘损毁=数据全失，这是底线保障。

### 恢复

```sh
cd /opt/moyu
gunzip -c backups/dom-<时间戳>.dump.gz \
  | docker compose exec -T postgres pg_restore -U dom_app -d dom --clean --if-exists
```

MinIO 恢复：把快照目录里的对象 `mc mirror` 回 `local/dom-assets`。

## 8. 回滚

镜像按本次源码构建：回滚 = 把代码切到上一发布点后重建（`docker compose --parallel 1 up -d --build`）。数据库 Migration 采用向后兼容模式（`docs/architecture/15` §68-71：Expand/Contract），回滚不应依赖不可逆 Schema 变更；如需迁库回滚，按对应 ADR/迁移记录执行。

## 9. 常见问题

| 现象 | 原因 / 处理 |
| --- | --- |
| gateway 一直 503 | 证书未签发。`docker compose logs certbot`；多半是安全组未放行 80。 |
| 拉镜像超时/失败 | 国内网络。配置 daemon.json registry-mirrors（§2.4），或 `.env` 设 `UV_IMAGE` / `NPM_REGISTRY` / `PYPI_INDEX_URL`。 |
| 注册后收不到验证码 | 默认 logging 邮件：看 `docker compose logs api` 里的 `dev-mail verification` 行。 |
| 编辑不同步 / WebSocket 连不上 | 确认 443 与 WebSocket 路径：浏览器 devtools → Network → WS → `wss://IP/v1/realtime`；`docker compose logs realtime`。 |
| 迁移失败后 api 起不来 | `docker compose logs migrate`；Alembic 幂等，修复后 `docker compose up -d migrate` 重跑。 |
| 想临时看 MinIO 控制台 | 不发布端口；控制台 9001 仅在容器内可达（distroless 无 shell，用 `docker compose exec minio` 无法进入；临时改 compose 把 9001 发布到 127.0.0.1 后用浏览器访问）。 |

## 10. 单机方案的边界（重要）

- 本方案是**单点部署**：ECS 故障 = 服务中断，数据卷丢失 = 数据不可恢复。它不是多实例高可用形态（`docs/architecture/15` 的生产目标）。
- 演进路径（按 ADR 0057）：换托管 PostgreSQL（RDS，改 `DATABASE_URL`）→ 应用镜像推阿里云 ACR + 多机 Compose → K8s。对象存储随时可切 OSS（S3 兼容接口不变）。