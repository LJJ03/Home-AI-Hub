# Home AI Hub

Home AI Hub 是基于 Python 3.13、FastAPI 和 PostgreSQL 17 的后端项目。目前已完成：

- Phase 3 Persistence Layer（Frozen）；
- Phase 4 LLM Provider Layer 公共契约（Frozen）；
- Phase 5 无状态 Chat API Layer（Frozen）；
- Phase 6 DeepSeek/OpenAI Provider Adapter、HTTP/SSE 基础设施和测试门禁。

Phase 6 已在 Python 3.13 环境完成正式默认测试并冻结，Git 基线 Tag 为 `v0.6.0`。
真实 DeepSeek/OpenAI Integration Tests 仍保持显式 opt-in，尚未运行时不得描述为通过。

Phase 7 的 Docker 动态验证、Default Offline CI、PostgreSQL Integration CI 和 Manual LLM
安全审批路径均已取得证据，现已冻结；annotated tag `v0.7.0` 已发布并固定指向
`5b411cb`，不得移动、删除或重建。真实 LLM Integration 仍为 `Not Run`，费用为 `0`。

Phase 8 Conversation Domain / Chat Persistence 已完成 Implementation Step 1–6；Step 6
commit `ac11520` 的 Default Offline CI 与 PostgreSQL Integration CI 均已通过。当前只进行
Step 7 Documentation、Release Gate Update 与 Freeze Preparation，尚未 Freeze。现有无状态
Chat API 保持不变，持久化 Conversation 能力通过独立 `/api/v1/conversations` API 提供。

## Docker 启动

Docker 开发配置源使用独立模板，默认是零密钥、零外部网络的 `mock` Provider：

仅在对应文件尚不存在时复制模板；已有配置应按字段差异合并，禁止直接覆盖。

```powershell
Copy-Item .env.docker.example .env.docker
docker compose --env-file .env.docker up --build
```

基础 Compose 明确读取 `.env.docker`，命令行的 `--env-file` 同时让 Compose 插值使用同一
配置源。Docker 开发不再要求或支持把 `.env.docker` 复制为 `.env`；Linux 或 macOS 使用
对应的 `cp` 命令。

Compose 会依次完成 PostgreSQL 健康检查、Alembic 自动迁移和 Backend 启动。Redis 独立
启动并执行自身健康检查，但尚未参与应用逻辑、Backend 启动依赖或 readiness。需要开发
日志增强时，可显式叠加覆盖文件：

```powershell
docker compose --env-file .env.docker -f docker-compose.yml -f docker-compose.dev.yml up --build
```

服务默认监听 <http://localhost:8000>：

- `GET /health`：进程存活检查，返回 `{"status":"ok"}`；
- `GET /ready`：应用与 PostgreSQL 就绪检查，不探测 LLM；
- `GET /version`：应用版本；
- `POST /api/v1/chat/completions`：无状态 Chat Completions，支持 JSON 与 SSE。
- `POST/GET /api/v1/conversations`：独立的持久化 Conversation API（当前只支持非流式 Turn）。

停止服务：

```bash
docker compose down
```

## 本地启动

项目正式运行基线为 Python 3.13：

以下复制命令同样只适用于尚不存在 `.env` 的首次初始化。

```powershell
Copy-Item .env.example .env
cd backend
python -m venv .venv
.venv\Scripts\python -m pip install -e ".[test]"
.venv\Scripts\python -m app
```

Linux 或 macOS 请使用 `.venv/bin/python`。

## Provider 选择

当前 Bootstrap 显式注册三个 Provider：

```text
LLM_PROVIDER=mock      -> MockProvider
LLM_PROVIDER=deepseek  -> DeepSeekProvider
LLM_PROVIDER=openai    -> OpenAIProvider
```

- `mock` 不需要 API Key，也不会访问外部网络；
- `deepseek` 需要 DeepSeek API Key、HTTPS Base URL 和默认模型；
- `openai` 需要 OpenAI API Key、HTTPS Base URL 和默认模型；
- 非选中 Provider 的 Key 可以为空；
- 配置缺失或 Provider 未注册会 fail fast，不会回退、降级或自动切换到 `mock`。

真实 Provider 通过内部 `httpx.AsyncClient` 和供应商无关 SSE Parser 接入，不安装
OpenAI、DeepSeek 或其他供应商 SDK。Base URL 和模型必须由环境变量提供，不在源码或
文档中写死。

完整配置、超时和部署说明见 [LLM Provider 运维指南](docs/operations/llm-providers.md)。

## Chat API 快速示例

非流式请求使用 `stream=false`（默认值）：

```bash
curl -X POST http://localhost:8000/api/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"messages":[{"role":"user","content":"Hello"}],"request_id":"demo-001"}'
```

流式请求设置 `stream=true`：

```bash
curl -N -X POST http://localhost:8000/api/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"messages":[{"role":"user","content":"Hello"}],"stream":true,"request_id":"demo-stream-001"}'
```

Chat API 公共 DTO 不因 Provider 改变，不暴露 `provider_request_id`、HTTP 对象、供应商
JSON 或异常。完整字段、SSE 帧和错误示例见 [Chat API 使用说明](docs/api/chat.md)。

## 测试

默认测试必须保持零真实密钥、零供应商账号和零外部网络：

```bash
cd backend
python -m pytest
```

GitHub Actions 默认离线 CI 会在每次 `push` 和 `pull request` 使用 Python 3.13 执行同一
命令。CI 不注入 GitHub secrets，不运行 PostgreSQL 或真实 LLM Integration，也不要求
Docker daemon。依赖安装阶段可能访问 Python 包仓库；测试执行阶段由项目 Network Gate
阻断公网 DNS 和 Socket，同时保留 TestClient/asyncio 所需的 loopback。

PostgreSQL Integration 使用独立 workflow，可在 `main` push 或手动触发时启动临时
PostgreSQL 17；真实 LLM Integration 则只能手动触发，并受成本确认与 GitHub protected
environment 审批约束。两个 Integration Workflows 都不属于默认 CI，其定义存在不代表
测试已经运行或通过。

PostgreSQL integration 使用独立开关：

```bash
cd backend
python -m pytest --run-integration
```

真实 LLM integration 必须同时显式传入开关和成本确认：

```bash
cd backend
LLM_INTEGRATION_ACKNOWLEDGE_COST=true python -m pytest --run-llm-integration
```

PowerShell：

```powershell
cd backend
$env:LLM_INTEGRATION_ACKNOWLEDGE_COST = "true"
python -m pytest --run-llm-integration
```

真实测试还要求目标 Provider 的 API Key、Base URL 和默认模型存在。缺少任一条件时只
跳过对应 Provider；`--run-integration` 与 `--run-llm-integration` 不会互相启用。
详细说明见[默认离线测试](docs/testing/default-tests.md)、
[PostgreSQL Integration 测试](docs/testing/postgres-integration.md)和
[LLM Integration 测试指南](docs/testing/llm-integration.md)。

## 配置与安全

应用使用 Pydantic Settings 读取进程环境变量和本地 `.env`。版本控制只保存 local、
docker、test 和 production sample 四类 example 模板；生产秘密必须由部署环境注入。

- API Key 使用 `SecretStr`，但仍禁止写入代码、提交记录、日志、异常和命令历史；
- Authorization Header、完整 Prompt、完整 Response 和完整流式 Chunk 不得记录；
- Provider Base URL 必须是无 userinfo、query、fragment 的 HTTPS URL；
- `LLM_CONNECT_TIMEOUT_SECONDS`、`LLM_READ_TIMEOUT_SECONDS` 和
  `LLM_STREAM_TIMEOUT_SECONDS` 缺失时继承 `LLM_TIMEOUT_SECONDS`；
- Stream timeout 是相邻流式事件之间的空闲上限，不是整个流的总时长；
- `/ready` 不远程探测 LLM，供应商健康应由受控运维检查单独判断。

模板选择、字段所有权和 fail-closed 规则见
[环境变量分层与安全边界](docs/operations/environment.md)。

## 架构文档

- [架构总览](docs/architecture/overview.md)
- [LLM Provider Layer](docs/architecture/llm-provider-layer.md)
- [Chat API Layer](docs/architecture/chat-api-layer.md)
- [Chat API 使用说明](docs/api/chat.md)
- [开发与架构规范](docs/development/standards.md)
- [Backend Runtime 运维说明](docs/operations/runtime.md)
- [Backend Docker 镜像说明](docs/operations/docker.md)
- [环境变量分层与安全边界](docs/operations/environment.md)
- [CI 与 Integration Workflows](docs/operations/ci.md)
- [Phase 7 Release Gate](docs/operations/release-gate.md)
- [Phase 8 Release Gate / Freeze Review Checklist](docs/operations/phase8-release-gate.md)
- [Runtime 与 Release Baseline ADR](docs/adr/0001-runtime-release-baseline.md)
- [Changelog](CHANGELOG.md)
- [LLM Provider 运维指南](docs/operations/llm-providers.md)
- [默认离线测试](docs/testing/default-tests.md)
- [PostgreSQL Integration 测试](docs/testing/postgres-integration.md)
- [LLM Integration 测试指南](docs/testing/llm-integration.md)

## 当前未实现范围

Phase 8 已新增独立 Conversation Persistence 与非流式 Conversation API，但没有修改既有
Chat API、ChatService、LLMService 或 Provider Interface 公共契约。当前仍未实现持久化
SSE、User/Auth/JWT、Redis 业务逻辑、RAG、Embeddings、向量数据库、文件上传、多模态、
WebSocket、Vue、Home Assistant、Agent、Tool/Function Calling、MCP、自动 Provider
fallback/routing/retry、成本统计或内容安全策略。
