# Changelog

本项目按里程碑记录可验证的架构与运行能力。`Not Run` 和 `Skipped` 不会被记录为
`Passed`。

## [Unreleased] — Phase 8 Conversation Domain / Chat Persistence

- Implementation Step 1–7 已完成：Domain、ORM/Migration、Repository/UoW、Application
  Service/Context Builder、独立 Conversation API Boundary、质量门禁和 Release Evidence；
- Step 6 增强跨层依赖、公开端点表面、无状态 Chat 回归和 Secret/Provider 隔离门禁；
- 新增显式 PostgreSQL-backed Conversation API production-wiring test，使用 MockProvider；
- Step 6 commit `ac11520` 的 Default Offline CI 与 PostgreSQL Integration CI 已在真实
  GitHub Runner 通过；
- Step 7 commit `ca05ab7` 的 Default Offline CI run `33528818430` 与 PostgreSQL
  Integration run `33528818472` 均为 `completed / success`；
- 首次 Freeze Review 已确认代码、测试、Runner、安全门禁和 Phase 3–7 冻结边界满足要求；
  当前正在进行 docs-only cleanup，cleanup commit 通过两项 Runner 后再执行最终 Freeze
  Review；
- Manual Real LLM run `33479758528` 已 `completed / cancelled`：DeepSeek cancelled、
  OpenAI skipped、deployment 未批准、Provider 未运行；
- 没有修改 Phase 3–7 冻结公共契约、Docker/Compose 或 GitHub workflow；
- Phase 8 尚未 Freeze 或正式发布，`v0.8.0` 尚未创建；`v0.7.0` 保持指向 `5b411cb`
  且不得移动、删除或重建；
- Real LLM Integration：`Not Run`；Real LLM Cost：`0`。

## [v0.7.0] — Phase 7 Runtime / Docker / CI / Release Gate（Freeze）

### Added

- Git 仓库、`main` 分支和 Phase 6 Freeze 基线；
- Python 3.13 多阶段、非 root Backend Runtime 镜像静态契约；
- local、Docker、test 和 production sample 环境模板；
- PostgreSQL 17、Redis 8、独立 Migration 和 Backend Compose 拓扑；
- Runtime、Environment、Compose、SDK Ban、Secret Hygiene 和 Freeze Regression 门禁；
- push/pull request 默认离线 CI；
- 独立 PostgreSQL Integration Workflow；
- 手动、成本确认、protected environment 约束的真实 LLM Integration Workflow；
- Release Gate 文档、ADR 和 Release Gate Contract Tests。

### Locally verified

- Python 3.13 默认全量 pytest；
- Runtime、Environment、Compose、CI、Integration Workflow 和架构静态契约；
- 默认测试的 Mock、零真实 API Key、Integration opt-in 和网络阻断语义；
- Phase 3–6 冻结边界没有生产代码回归。

### Runtime verification passed

- 云服务器 Docker Engine 与 Docker Compose 可用；
- Docker image dynamic build/run 通过，Python `3.13.15`、UID `10001` 非 root 已验证；
- Compose 中 PostgreSQL 17、Redis 8 和 Backend healthy；
- Migration container code `0`，`alembic_version=20260826_0001`；
- `/health`、`/ready`、`/version`、Mock Chat JSON 和 Mock Chat SSE 通过；
- GitHub remote 配置、`main` push 和 `v0.6.0` tag push 通过。

### GitHub Runner verification passed

- GitHub account Billing Lock 已由 GitHub Support 解除；
- Default Offline CI 已在真实 GitHub Runner 上执行并通过；
- PostgreSQL Integration CI 已在真实 GitHub Runner 上执行并通过；
- Manual Real LLM Integration 的费用确认 fail-closed 和 protected environment 人工审批路径已验证；
- 授权费用确认后，DeepSeek job 曾停在 `Waiting for review`，随后已取消；OpenAI job 为
  `Skipped`；
- deployment 未获批准，真实 Provider 未运行，费用为 `0`。

### Release

- Annotated tag `v0.7.0` 已创建并推送至 `origin`；
- `v0.7.0` 指向 commit `5b411cb`；
- GitHub Runner、Docker Dynamic Verification 和本地 Release Gate 证据已齐；
- 已发布 tag 不得移动、删除或重建。

### Historical blocker resolved

- GitHub 默认 CI 的 Runner execution 曾因 Billing Lock 未启动；当前已由后续真实 Runner
  `Passed` 证据取代；
- GitHub Actions 曾因账号 Billing Lock 拒绝启动 job；该外部账号阻塞现已解除；
- Billing Lock 期间的失败记录只代表 job 未启动，不代表 Workflow 或测试失败；
- 解除后已重新触发并取得上述 Default Offline CI 与 PostgreSQL Integration CI 的真实 Runner 证据。

### Not Run

- Real DeepSeek/OpenAI Integration；
- 生产 Secret Manager、反向代理 SSE 和 image digest promotion 验证。

Real LLM Integration：`Not Run`。Real LLM Cost：`0`。没有配置或运行真实
OpenAI/DeepSeek Key。

该 Release 的状态：**Freeze（`v0.7.0`）**。创建 `v0.7.0` 时，Phase 8 Architecture
Design 已完成、Implementation 尚未开始；当前开发进度记录在上方 `Unreleased` 段落。

历史状态（已结束）：Phase 7 — Runtime, Docker, CI and Release Gate Freeze Pending。

## [v0.6.0] — Phase 6 Freeze baseline

- Commit 基线：`1afd8a4`；
- 冻结 Real LLM Provider Adapters 及 Phase 4/5 公共契约边界；
- 默认离线 pytest 已在 Python 3.13 环境通过；
- 真实 DeepSeek/OpenAI Integration 保持未运行和显式 opt-in。
