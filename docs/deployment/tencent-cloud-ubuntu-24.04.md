# 腾讯云 Ubuntu 24.04 部署准备

状态：方案待确认；尚未连接或修改腾讯云资源。

## 推荐方案

如果第一阶段明确限定为一台腾讯云 CVM，建议把它作为应用主机，使用 Docker Compose 运行 Web、API、Realtime 和 Worker；大型文件存入腾讯云 COS，PostgreSQL 使用腾讯云高可用实例。该方案部署简单，适合先上线验证，但单台 CVM、单实例 NATS 和 Valkey 仍是可用性单点，不等同于高可用生产架构。

项目当前冻结的生产部署目标是 Kubernetes + Helm + Terraform（`docs/architecture/26-Technology-Stack-Decision.md`）。因此，单 CVM Compose 只能作为明确批准的第一阶段例外。另一条路径是按冻结方案部署 Kubernetes 集群并使用 Helm；它支持横向扩展，但不再是把整套应用直接装到一台独立 Ubuntu 服务器上。

| 选项 | 适用目标 | 主要代价 |
| --- | --- | --- |
| 单 CVM + Compose + COS + 托管 PostgreSQL | 先在指定 Ubuntu 服务器运行一套实例 | CVM、NATS、Valkey 单点；需要批准偏离当前生产部署约束 |
| Kubernetes + Helm + Terraform + COS + 托管 PostgreSQL | 面向多实例与可用性要求的生产环境 | 需要集群、云资源配置和更完整的运维准备；不是单机部署 |

## 存储配置

- 本地 Compose 使用 MinIO；腾讯云环境使用私有 COS Bucket，不把用户文件保存在 CVM 系统盘。
- COS 配置使用 `S3_ASSET_ENDPOINT=https://cos.<region>.myqcloud.com`、`S3_ASSET_REGION=<region>`、`S3_ASSET_BUCKET=<bucket>-<appid>` 和 `S3_ASSET_ADDRESSING_STYLE=virtual`。
- 代码中的 S3 Asset Store 已支持 `path` 与 `virtual` 寻址。COS 新 Bucket 需要 virtual-hosted-style；本机 MinIO 的 path-style 上传、读取、删除已通过运行时回环验证。当前没有 COS Bucket 和凭据，因此尚未完成真实 COS 请求验证。
- 使用仅授权目标 Bucket 的 CAM 子用户密钥；密钥只放在服务器的权限受限环境文件或密钥服务中，不提交到 Git。

## 主机与网络准备

- CVM 系统：Ubuntu Server 24.04 LTS 64-bit。先在实例上用 `uname -m` 确认 `x86_64` 或 `aarch64`，构建与运行镜像时保持同一架构。
- 安装 Docker Engine 与 Compose 插件，使用 Docker 官方 Ubuntu 软件源；官方安装文档支持 Ubuntu Noble 24.04。
- 域名、TLS 终止位置、地域、VPC、安全组和备份周期尚未提供，需在选定部署路径后确定。
- 公网入口只开放实际使用的 SSH、HTTP、HTTPS 端口，并限制 SSH 来源；PostgreSQL、NATS、Valkey、COS 凭据和管理端口不暴露公网。
- 当前 `compose.yaml` 是本地开发栈：包含本地 PostgreSQL 与 MinIO，Web 只绑定 `127.0.0.1:5180`。不要直接把它当作服务器生产配置。批准服务器路径后再创建独立服务器 Compose 或 Helm 配置。

## 腾讯云资源清单

| 资源 | 准备要求 |
| --- | --- |
| CVM | Ubuntu 24.04 LTS 64-bit；确认 CPU 架构、CPU、内存和数据盘后再确定规格 |
| COS | 与应用就近的地域；私有 Bucket；记录地域、Bucket 全名和 APPID；配置最小权限 CAM 密钥 |
| PostgreSQL | 与 CVM 同地域、同 VPC 的 PostgreSQL 18 高可用实例；建立独立数据库与最小权限账号 |
| 域名与 TLS | 准备域名及 DNS 管理权，确定由主机入口还是云负载均衡终止 TLS |
| 部署凭据 | 服务器专用环境文件或密钥服务；不写入仓库、不放入 README |

## 服务器配置仍需落实

批准单机 Compose 路径后，需要为服务器补充独立配置：外部 PostgreSQL、COS virtual 寻址、生产密钥、TLS 入口、容器资源限制、日志轮转、备份与恢复步骤。当前本地 `compose.yaml` 不包含这些生产设置。

可参考：[Docker Engine Ubuntu 安装文档](https://docs.docker.com/engine/install/ubuntu/)、[Docker Compose Linux 安装文档](https://docs.docker.com/compose/install/linux/)、[腾讯云 COS S3 兼容配置](https://intl.cloud.tencent.com/document/product/436/34688?lang=en)、[COS 域名寻址说明](https://cloud.tencent.com/document/product/436/102489)、[腾讯云 PostgreSQL 高可用与版本说明](https://cloud.tencent.com/document/product/409/7562)。
