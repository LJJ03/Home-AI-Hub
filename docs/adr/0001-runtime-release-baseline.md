# ADR 0001：Runtime 与 Release Baseline

- 状态：Accepted
- 日期：2026-08-29
- 决策范围：Phase 7 Runtime、Docker、CI 与 Release Gate

## 背景

Phase 3–6 已建立 Persistence、LLM Provider、无状态 Chat API 和真实 Provider Adapter。
Phase 7 需要让同一代码基线能够被重复测试、构建、迁移和发布，同时保持真实 LLM 成本、
秘密及外部网络均为显式授权能力。

## 决策

1. 项目 Runtime 使用 Python 3.13，`pyproject.toml` 只接受 `>=3.13,<3.14`；
2. Backend Runtime 镜像固定 Python 3.13，采用多阶段构建并以非 root 用户运行；
3. Migration 使用与 Backend 相同的镜像，但作为独立一次性服务执行；
4. Backend 不自行执行 Migration，Migration 失败必须阻止 Backend 启动；
5. 默认 Provider 为 `mock`，默认测试零真实 API Key、零供应商账号、测试阶段零外部网络；
6. PostgreSQL Integration 与默认 CI 分离，不响应 pull request；
7. 真实 LLM Integration 只能手动触发，必须人工确认成本，并通过 protected environment
   只注入被选 Provider 的配置；
8. Release Gate 使用 `Passed`、`Skipped`、`Not Run` 和 `Failed`，绝不把 `Not Run` 写成
   `Passed`；
9. Tag 只能建立在全部硬门禁有实际证据的 clean commit 上；
10. Docker 动态验证尚未执行时，Phase 7 状态只能是 `Freeze Pending`。

## 结果

这一决策让默认开发和 PR 验证保持确定、离线且无费用，同时为数据库和真实 Provider 提供
受控路径。代价是静态契约通过不足以发布：Docker、Compose 和 GitHub Runner 必须提供独立
动态证据，真实 Provider 验证还需要审批、秘密配置和成本承担。

当前机器没有 Docker/Podman/nerdctl/buildah，三个 GitHub Workflows 也尚未在 Runner
执行。因此当前结论是 **Phase 7 — Runtime, Docker, CI and Release Gate Freeze Pending。**

## 冻结边界

- Persistence 只由 Alembic/Repository 边界扩展，不反向依赖 LLM、Runtime 或 CI；
- Provider Interface、DTO、异常和 LLMService 继续遵循 Phase 4 Freeze；
- 无状态 Chat Completions JSON/SSE 继续遵循 Phase 5 Freeze；
- Chat API 不调用具体 Provider，Bootstrap 保持唯一组合根；
- 不增加自动 fallback、retry、Provider routing 或 LLM readiness 探活。

## 替代方案

- 仅依赖静态 Dockerfile/Compose 测试：拒绝，因为不能证明镜像实际构建和启动；
- 默认 CI 运行全部 Integration：拒绝，因为会引入数据库资源、真实秘密、外部网络和费用；
- Backend 启动时自动 Migration：拒绝，因为多副本并发和失败可见性不可控；
- 未完成动态验证即创建 `v0.7.0`：拒绝，因为 tag 会错误表达可发布状态。
