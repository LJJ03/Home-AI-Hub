# Changelog

本项目按里程碑记录可验证的架构与运行能力。`Not Run` 和 `Skipped` 不会被记录为
`Passed`。

## [Unreleased] — Phase 7 Freeze Pending

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

### Blocked

- GitHub 默认 CI 的 Runner execution / Default Offline CI：GitHub account billing lock，job 未启动；
- GitHub PostgreSQL Integration Workflow execution / PostgreSQL Integration CI：GitHub account billing lock，job 未启动；
- 该阻塞属于外部账号状态，不得记为 Workflow `Passed`；解除 Billing Lock 后必须重新触发。

### Not Run

- GitHub Manual LLM Integration Workflow execution；
- Real DeepSeek/OpenAI Integration；
- 生产 Secret Manager、反向代理 SSE 和 image digest promotion 验证。

Real LLM Cost：`0`。没有配置或运行真实 OpenAI/DeepSeek Key。

当前状态为 **Phase 7 — Runtime, Docker, CI and Release Gate Freeze Pending。**
GitHub Actions Billing Lock 和上述未运行项尚未解除；当前不得创建 `v0.7.0` tag。

## [v0.6.0] — Phase 6 Freeze baseline

- Commit 基线：`1afd8a4`；
- 冻结 Real LLM Provider Adapters 及 Phase 4/5 公共契约边界；
- 默认离线 pytest 已在 Python 3.13 环境通过；
- 真实 DeepSeek/OpenAI Integration 保持未运行和显式 opt-in。
