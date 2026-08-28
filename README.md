# Home AI Hub

Home AI Hub 是基于 Python 3.13、FastAPI 和 PostgreSQL 17 的后端项目。目前已完成：

- Phase 3 Persistence Layer（Frozen）；
- Phase 4 LLM Provider Layer 公共契约（Frozen）；
- Phase 5 无状态 Chat API Layer（Frozen）；
- Phase 6 DeepSeek/OpenAI Provider Adapter、HTTP/SSE 基础设施和测试门禁。

Phase 6 的代码、离线测试设计、显式真实 Integration Tests 和静态质量门禁已经完成，
但当前机器尚未在项目 Python 3.13 环境成功执行正式全量 `python -m pytest`。因此当前
状态是 **Phase 6 Freeze Pending / 待正式 pytest 验证**，不能声明 Phase 6 已正式冻结。

## Docker 启动

默认 `.env.example` 使用零密钥、零外部网络的 `mock` Provider：

```bash
docker compose up --build
```

Compose 会依次完成 PostgreSQL 健康检查、Alembic 自动迁移和 Backend 启动。Redis 独立
启动，但尚未参与应用逻辑或 readiness。

服务默认监听 <http://localhost:8000>：

- `GET /health`：进程存活检查，返回 `{"status":"ok"}`；
- `GET /ready`：应用与 PostgreSQL 就绪检查，不探测 LLM；
- `GET /version`：应用版本；
- `POST /api/v1/chat/completions`：无状态 Chat Completions，支持 JSON 与 SSE。

停止服务：

```bash
docker compose down
```

## 本地启动

项目正式运行基线为 Python 3.13：

```powershell
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
详细说明见 [LLM Integration 测试指南](docs/testing/llm-integration.md)。

## 配置与安全

应用使用 Pydantic Settings 读取环境变量和本地 `.env`，受版本控制的模板为
`.env.example`。

- API Key 使用 `SecretStr`，但仍禁止写入代码、提交记录、日志、异常和命令历史；
- Authorization Header、完整 Prompt、完整 Response 和完整流式 Chunk 不得记录；
- Provider Base URL 必须是无 userinfo、query、fragment 的 HTTPS URL；
- `LLM_CONNECT_TIMEOUT_SECONDS`、`LLM_READ_TIMEOUT_SECONDS` 和
  `LLM_STREAM_TIMEOUT_SECONDS` 缺失时继承 `LLM_TIMEOUT_SECONDS`；
- Stream timeout 是相邻流式事件之间的空闲上限，不是整个流的总时长；
- `/ready` 不远程探测 LLM，供应商健康应由受控运维检查单独判断。

## 架构文档

- [架构总览](docs/architecture/overview.md)
- [LLM Provider Layer](docs/architecture/llm-provider-layer.md)
- [Chat API Layer](docs/architecture/chat-api-layer.md)
- [Chat API 使用说明](docs/api/chat.md)
- [开发与架构规范](docs/development/standards.md)
- [Backend Runtime 运维说明](docs/operations/runtime.md)
- [Backend Docker 镜像说明](docs/operations/docker.md)
- [LLM Provider 运维指南](docs/operations/llm-providers.md)
- [LLM Integration 测试指南](docs/testing/llm-integration.md)

## 当前未实现范围

Phase 6 没有改变 Chat API、ChatService、LLMService、Provider Interface 或 Persistence
Layer 公共契约，也没有实现数据库聊天存储、聊天历史、Conversation/Message/User ORM
模型、认证、JWT、Redis 逻辑、RAG、Embeddings、向量数据库、文件上传、多模态、
WebSocket、Vue、Home Assistant、Agent、Tool/Function Calling、MCP、自动 Provider
fallback/routing/retry、成本统计或内容安全策略。
