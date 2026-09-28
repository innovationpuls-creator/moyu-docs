# 开发原则

先理解项目，再决定怎么改。
开发前了解项目技术栈、当前模块、已有依赖和现有实现。能合理满足项目目标的已有技术栈、依赖、函数、类、定义和 API 优先复用，不重复造轮子。
方案选择以项目目标及其指标优先级为准，不以最小改动为目标。现有代码若因兼容、重复实现或层层适配成为负担，应考虑重构或重写，而不是继续堆补丁。
不要进行与目标无关的修改；但当目标的正确实现需要调整现有结构时，不受最小改动或原任务文件范围限制。重大范围扩张先给方案确认。
不得为了单个问题、样例或测试结果专项优化 Prompt、代码或参数。修改应针对通用原因，避免当前案例变好而整体表现变差。
性能结论必须由 benchmark、profiling、压测或其他量化测试证明，具体指标及优先级按项目目标决定。

## 方案与变更

影响项目的重大技术变化需要方案对比和 ADR，存放于 `docs/adr/NNNN-short-name.md`。ADR 记录 Context / Decision / Alternatives / Consequences / Migration / Rollback。具体 ADR 流程不放在本文件中。

## Architecture Constitution 加载规则

任何实现任务开始前：

1. 读 `docs/architecture/00-ARCHITECTURE-CONSTITUTION.md`。
2. 定位该任务的 Canonical Owner 文档。
3. 只加载该 Owner 文档 + 它点名的直接依赖。
4. 读目标模块的 `README.md`。
5. 检查依赖方向后，才改代码。

禁止默认把 `docs/architecture/01`–`29` 全部塞进上下文。
冲突解决顺序：Constitution > Canonical Owner > Specialized Subordinate Design > Example / Recommendation。
实现请求与 Constitution 冲突时，先报告冲突再决定，不要直接改代码。
`PRODUCT_DECISION_PENDING` 不是猜的许可：停下该产品分支并询问，同时继续无关工程工作。
本文件与代码注释不复制架构文档正文；需要时给出 `docs/architecture/NN-*.md §X` 引用。

## 模块边界

技术栈由 `docs/architecture/26` 冻结，仓库布局与依赖方向由 `docs/architecture/27` 冻结：

- Web 在 `apps/web`；API 在 `services/api`；Realtime 在 `services/realtime`；Worker 在 `workers/*`。
- Python Domain / Application Core 在 `packages/py/core`；基础设施适配器在 `packages/py/infrastructure`；通用 Task Runtime 在 `packages/py/task-runtime`。
- TS 客户端运行时在 `packages/ts/*`；Contract 源头在 `/contracts`；PostgreSQL Migration 在 `/migrations/postgres`。
- 依赖方向：

```text
services/api  → core.application → core.domain
infrastructure ↑ implements core.ports
workers       → task-runtime     → core.application

apps/web → client-sdk / resource-runtime / editor-core / realtime-client → contracts
services/realtime → packages/ts/contracts + Yjs + pg + NATS   （禁止 import apps/web）
contracts 不依赖任何 Application Module
```

- 每个 Domain 模块统一 `domain/ application/ ports/ README.md`；`domain` 不 import Framework / Infrastructure。
- 每张 PostgreSQL 表有唯一 Domain Owner，非 Owner 模块不得写该表。逻辑模型与事务边界见 `docs/architecture/29`。
- 跨模块机器契约必须在 `docs/architecture/28` 的 Registry 注册；禁止手写第二份 DTO。

## 质量门槛

- 没有失败的测试就不算实现；不得声称未经实际执行的测试、功能或性能结果已通过。
- 性能结论必须由 benchmark / profiling / 压测或其他量化测试证明。

## 禁止跨层实现

- 不以 mock、假数据、fallback、silent catch 或默认返回值掩盖真实问题和异常。

## 自动化代码净化与类型约束

  - 前端/TS/JSON 修改：每次修改代码后，必须执行 `pnpm exec biome check --write <file_path>`（或 `just format-js`），清除废弃引用并对齐格式。
  - 后端/Python 修改：每次修改代码后，必须执行 `uv run ruff check --fix <file_path>` 与 `uv run ruff format <file_path>`（或 `just format-py`），拦截 F401（未用导入）、F841（未用变量）、排序 import 并格式化。
  - 全局一键净化：在根目录下执行 `just format` 或 `just lint`。

## 不要

- 不要为了形式上的面面俱到，自行加入“可测试、可维护、可扩展、符合现有架构/目录/命名/日志/配置/测试风格”等未要求的目标。
- 不要声称未经实际验证的功能、测试或性能结果已经成功。
- 不要自行开分支，完成一个阶段就提交，使用中文简单描述。
- 不要硬编码 secret、API key 或其他凭据。

