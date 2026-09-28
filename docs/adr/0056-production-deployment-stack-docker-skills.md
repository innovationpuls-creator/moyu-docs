# ADR-0056: 生产部署技术栈交由 docker skills 决策

## Status

Accepted

## Context

项目此前在 `docs/architecture/26-Technology-Stack-Decision.md` 中把正式多实例高可用生产锁定为 Kubernetes + Helm + Terraform（编排、打包、IaC 一体），Edge 锁定为 Gateway API + Envoy Gateway，Secrets 锁定为 External Secrets Operator。

此后用户移除了仓库内全部 Docker 部署产物（compose.yaml、Dockerfile、部署脚本、部署手册与 ADR 0053-0055），并安装了 docker/skills 技能包（`docker-project-foundations`、`docker-build-strategies`、`docker-compose-patterns`、`docker-destructive-guardrails`），期望由这些技能在具体任务中主导容器化与部署决策。

继续在架构文档里锁定"生产 = Kubernetes + Helm"会与技能驱动的部署方式产生文档级冲突：后续 AI 加载文档后会优先选择 Kubernetes/Helm，而不是按项目实际目标由 docker skills 判断（可能是 Docker Compose 或其它编排方案），并会为不存在于仓库的平台产物创建虚假的目录、打包与编排假设。

## Decision

解除 26 中对生产部署技术栈的平台锁定，把部署决策权交由 docker skills：

- **ORCHESTRATOR**：生产编排方式由 docker skills 按项目目标在部署时决策，不再锁定具体平台（Kubernetes / Docker Compose / 其他）。
- **Deployment Package**：随编排方案决策，不锁定 Helm。
- **Infrastructure as Code**：保留 Terraform 作为云资源 IaC 的推荐选择，允许按部署方案选择等价工具。
- **Edge**：入口方案随部署决定（支持 HTTPS / WSS 长连接的要求不变），不锁定 Gateway API + Envoy Gateway。
- **Secrets**：管理方式随部署方案决策，保留硬规则"Secret 不进入 Git / 明文 values"。
- 多实例高可用作为生产**目标**保留（硬约束 14），仅解除具体平台锁定。

同步修正 `docs/architecture/15`（"第一版不做"列表中删除"所有服务 Kubernetes 化才可运行"的锁定语义；§135 自由度条目注明由 docker skills 决策）与 `docs/architecture/20`（Edge 一行不再锁定 Gateway API + Envoy Gateway），并删除 `docs/architecture/27` 中 `infra/` 目录规划里的 `helm/`、`envoy/` 与对应小节（保留 `terraform/`、`otel/`、`nats/`、`opensearch/`、`grafana/`）。

## Alternatives

- **保留 Kubernetes + Helm 锁定**：与技能驱动部署产生文档冲突，后续本地 AI 会被引导到仓库中不存在的平台上。拒绝。
- **把锁定改为 Docker Compose**：同样属于预先锁定平台，违背"由技能按项目目标决策"的意图，且 Compose 与未来多实例/多机规模需求未必匹配。拒绝。
- **为生产锁定写新 ADR 替换**：不预设任何平台，把选择留给执行时的技能决策，避免再次产生过时锁定。采纳前者。

## Consequences

- 架构文档不再声明"生产 = Kubernetes + Helm"，后续 AI 依据 docker/skills 的 four skills 按项目现状决策部署形态。
- 多实例高可用仍是生产硬性目标；编排、打包、Edge、Secrets 的具体产品选择推迟到部署执行阶段。
- `docs/architecture/26` §55（Container：OCI Image / multi-stage / non-root）保留不变——容器镜像基本规范与平台选择无关。
- 本地开发继续使用开发者自备依赖（ADR 0056 前已确立），与技能指导的 Docker 化互不冲突：技能负责"是否容器化、如何写 Dockerfile/compose"，本地宿主开发仍可按 README 运行。

## Migration

1. 修改 `docs/architecture/26` §56-§60、技术栈汇总表的 Production HA / Edge / Secrets 行、硬约束 14。
2. 修改 `docs/architecture/15` §126 与 §135。
3. 修改 `docs/architecture/20` §161。
4. 修改 `docs/architecture/27` §59 infra 目录规划与删除 §61 helm 小节。
5. 本 ADR（0056）落库。后续如按技能决策实际选定某生产平台，再以新 ADR 锁定选型结果。

## Rollback

恢复 `docs/architecture/26` §56-§60 为 Kubernetes + Helm + Terraform 与 Gateway API + Envoy Gateway、`27` 的 `infra/helm/`、`infra/envoy/` 目录规划，并回退 15/20 的措辞。此回滚不涉及运行时数据或代码，仅文档状态。