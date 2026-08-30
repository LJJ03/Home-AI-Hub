# Phase 7 Release Gate

## 目标与当前结论

Release Gate 为 Runtime、Docker、环境分层、Compose、CI 和 Integration Workflows 提供一份
可审计的发布判定。它只接受实际执行证据，不用静态检查代替动态检查，也不把有意跳过的
测试计为通过。

当前结论：**Phase 7 — Runtime, Docker, CI and Release Gate Freeze Pending。**

Docker 动态验证已在云服务器完成并通过。GitHub remote、`main` 和 `v0.6.0` tag 已推送，
但 GitHub Actions job 因账号 Billing Lock 未能启动，因此仍不满足正式 Freeze 的硬门禁，
也不得创建 `v0.7.0` tag。

## 状态分类

| 状态 | 语义 | 是否满足对应硬门禁 |
|---|---|---|
| `Passed` | 指定检查已实际执行且成功，并有命令、环境和结果证据 | 是 |
| `Skipped` | 测试被收集，但因明确的 opt-in 策略未启用 | 否，不得计为 Passed |
| `Not Run` | 因工具、Runner、授权或目标环境不可用而没有执行 | 否，不得计为 Passed |
| `Blocked` | 已请求执行，但被外部账号、平台或审批条件阻止，job 未实际启动 | 否，解除阻塞后必须重新执行 |
| `Failed` | 检查已执行但失败，或证据/边界不符合要求 | 否，必须停止发布 |

未运行不能写成通过。`Skipped`、`Not Run` 和 `Blocked` 必须保留原因；不得用“预期可
通过”“静态已覆盖”或 Workflow 已创建替代运行证据。

## 当前可执行门禁

在项目 Python 3.13 环境执行：

```console
cd backend
python -m pytest
```

该命令必须覆盖并通过 Runtime、Environment、Compose、Quality、Architecture、默认 CI、
Integration Workflow 和 Release Gate Contract Tests。默认测试必须保持 Mock Provider、
零真实 API Key、零供应商账号和测试阶段零外部网络。PostgreSQL 与真实 LLM Integration
在默认运行中应显示为 `Skipped`，而非 `Passed`。

本地 Release Gate 还要审查 Git 状态：工作树必须 clean，或只包含当前已审核步骤的预期
变更；生产代码、冻结契约、Dockerfile 行为和 Compose 拓扑不得出现越界修改。

## 显式 Integration 命令

PostgreSQL 17 Integration：

```console
cd backend
python -m pytest --run-integration
```

真实 LLM Integration 只能在明确授权、成本确认和目标 Provider 配置齐全后运行：

```console
cd backend
LLM_INTEGRATION_ACKNOWLEDGE_COST=true python -m pytest --run-llm-integration
```

两类开关互不授权。真实 LLM 运行必须记录目标 Provider、审批和费用风险，但不得记录 API
Key、Authorization Header、Prompt、完整 Response、完整 Chunk 或供应商错误体。

## Docker 动态验证

在有 Docker 的受控环境中，从项目根目录执行：

```console
docker build --tag home-ai-hub-backend:release-candidate backend
docker run --rm home-ai-hub-backend:release-candidate python --version
docker run --rm --entrypoint id home-ai-hub-backend:release-candidate
docker compose --env-file .env.docker config
docker compose --env-file .env.docker up --build --detach
```

验证 Migration service 成功后执行 Compose Smoke Test：

```console
curl --fail http://localhost:8000/health
curl --fail http://localhost:8000/ready
curl --fail http://localhost:8000/version
docker compose --env-file .env.docker down
```

必须分别记录镜像 build、镜像 run、容器非 root 身份、Compose config、Compose up、实际
Migration、`/health`、`/ready` 和 `/version`。清理命令不应删除未知 volume 或工作区数据。

当前云服务器验证记录（Passed）：

- Docker Engine 与 Docker Compose 可用；
- Backend image build 通过，容器 Python 为 `3.13.15`；
- 容器 UID 为 `10001`，非 root 运行已验证；
- `docker compose up` 通过；
- `postgres:17-alpine`、`redis:8-alpine` 和 Backend healthy；
- Migration container 以 code `0` 退出，`alembic_version=20260826_0001`；
- `/health`、`/ready` 和 `/version` 均通过；
- Mock Chat JSON 与 Mock Chat SSE 均通过；
- 未运行真实 LLM，供应商费用为 `0`。

以下是已被上述云服务器证据取代的 Step 8 本机历史记录，不代表当前状态：

> Docker dynamic verification: Not Run — Docker/Podman/nerdctl/buildah unavailable on this machine.

## GitHub Actions 运行证据

Workflow 文件和静态契约通过不代表 GitHub Runner 已执行。必须分别保存默认 CI、
PostgreSQL Integration 和 Manual LLM Integration 的 run URL、commit SHA、触发方式、状态
和时间；日志不得包含秘密或模型内容。

GitHub remote 发布记录（Passed）：

- `origin` 指向项目 GitHub repository；
- `main` 已推送；
- Phase 6 Freeze tag `v0.6.0` 已推送。

GitHub Actions Runner Validation 当前记录：

> Default Offline CI: Blocked by GitHub account billing lock.

> PostgreSQL Integration CI: Blocked by GitHub account billing lock.

GitHub 显示的阻塞原因为：`The job was not started because your account is locked due to a billing issue.`
两个 job 均未启动，因此不能记为 `Passed` 或测试失败；解除账号 Billing Lock 后必须重新触发。

> Manual Real LLM Integration: Not Run.

> Real LLM Integration: Not Run — no authorized provider run was performed and no provider cost was incurred.

> Real LLM Cost: 0.

以下是已被 Billing Lock 诊断取代的 Step 8 历史记录，不代表当前 Runner 状态：

> GitHub Actions runtime execution: Not Run — workflows created but not triggered on GitHub Runner.

> PostgreSQL Integration workflow: Not Run — workflow created but not triggered on GitHub Runner.

## 部署环境手动门禁

以下项目不能由当前本地静态门禁写成 `Passed`，必须在特定上线环境单独执行并记录：

- Provider-specific validation；
- Production Secret Manager 注入、轮换和撤销验证；
- Reverse proxy SSE buffering、idle timeout 和长连接上限验证；
- Image digest promotion 与部署平台拉取验证；
- 真实 LLM Integration（仅在明确授权和成本确认后）。

## Freeze 与 Freeze Pending

Phase 7 只有在以下硬条件都有 `Passed` 证据时才能正式 Freeze：

1. Python 3.13 默认全量 pytest；
2. Runtime、Environment、Compose、Quality、Architecture 和 Release Contract Gates；
3. SDK Ban、Secret Hygiene 和 Phase 3–6 Freeze Regression；
4. Docker image build/run、非 root 身份及 Compose config/up；
5. Migration container 和三个系统端点的动态 Smoke Test；
6. GitHub 默认 CI 的真实 Runner 执行；
7. PostgreSQL Integration Workflow 的真实 Runner 执行；
8. Manual LLM Workflow 的安全审批路径得到验证；如不授权产生费用，真实调用继续明确记录
   为 `Not Run`，不得伪装为 Provider 已验证。

任一硬门禁为 `Not Run`、`Skipped`、`Blocked` 或 `Failed` 时，状态必须保持
`Freeze Pending`。Docker 动态门禁现已通过；当前 Default Offline CI 与 PostgreSQL
Integration CI 被 GitHub 账号 Billing Lock 阻塞，Manual Real LLM Integration 未运行，
因此只能保持 Pending。

## Tag 策略

- `v0.6.0` 保持 Phase 6 Freeze 基线；
- Pending 状态不得创建或移动 `v0.7.0`；
- 全部硬门禁通过后，在已审核且 clean 的基线 commit 上创建 annotated `v0.7.0` tag；
- Tag 注释只记录可公开的测试摘要和证据引用，不包含凭据、数据库 URL 或模型内容；
- 已发布 tag 不得重写；修复应产生新 commit，并按版本策略创建后续 tag。

## 回滚注意事项

Runtime 回滚应重新部署上一已验证 tag 或不可变镜像 digest，而不是在运行容器中修改文件。
数据库 Migration 不自动 downgrade；回滚前必须检查新旧应用与当前 schema 的兼容性，并为
破坏性 schema 变更准备单独审核的前向修复或人工回滚方案。Provider、Chat API 和
Persistence 的公共契约不能因运行时回滚而被绕过。

## Phase 3–6 冻结边界

- Persistence Layer 不得反向依赖 Runtime、CI 或 LLM；Schema 只通过 Alembic Migration；
- Phase 4 Provider Interface、DTO、异常和 LLMService 契约不得修改；
- Phase 5 无状态 Chat Completions JSON/SSE 语义不得修改；
- Chat API 不感知具体 Provider，ChatService 只调用 LLMService；
- Bootstrap 仍是具体 Provider 唯一组合根，Factory 只通过冻结 Registry 创建 Provider；
- 不得增加静默 fallback、自动 retry、自动 Provider routing 或 LLM `/ready` 远程探活。
