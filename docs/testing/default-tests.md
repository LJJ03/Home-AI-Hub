# 默认离线测试

## 运行方式

在项目 Python 3.13 环境执行：

```console
cd backend
python -m pytest
```

默认测试不要求复制任何环境模板，也不要求 PostgreSQL、Redis、供应商账号或真实 API
Key。需要显式环境样例时只能从 `.env.test.example` 开始，并保持 Provider 为 `mock`、
成本确认为关闭状态。

默认质量基线是：零真实 API Key、零供应商账号、零外部网络、零 Docker daemon 依赖。

## GitHub Actions 默认离线 CI

`.github/workflows/ci.yml` 在 `push` 和 `pull request` 时运行，使用显式 Python 3.13，
并在 `backend/` 中依次执行：

```console
python -m pip install --upgrade pip
python -m pip install -e ".[test]"
python -m pytest
```

依赖安装阶段可能需要访问 Python 包仓库。测试执行阶段依靠仓库的 autouse Network Gate
阻断公网 DNS、Socket 和真实供应商域名，只允许本机 loopback。默认 CI：

- 固定 `LLM_PROVIDER=mock`，不读取 GitHub secrets；
- 不需要真实 API Key 或供应商账号；
- 不运行 PostgreSQL Integration；
- 不运行真实 LLM Integration；
- 不传入 `--run-integration` 或 `--run-llm-integration`；
- 不启动 Docker、Compose、PostgreSQL、Redis 或真实 Provider；
- 不产生供应商费用。

Dockerfile 和 Compose 在默认测试中只接受静态契约检查，不要求本机 Docker daemon。
Phase 7 的 Docker 动态验证已在独立云服务器通过；该历史运行证据不改变默认 pytest 的
离线职责。PostgreSQL 与真实 LLM Integration Workflows 已独立定义；
默认 CI 不运行 Integration Workflows，也不获得其服务、成本授权或 secrets。

## 安全语义

默认测试通过自动 fixture 阻断外部 DNS 和 Socket，只允许 TestClient、asyncio 和 Windows
self-pipe 所需的本机 loopback。`httpx.MockTransport` 保持离线，不因网络门禁受影响。

默认测试必须：

- 使用 Mock Provider 或 MockTransport；
- 不访问真实 PostgreSQL；
- 不访问真实 DeepSeek/OpenAI；
- 不读取或要求真实 Provider API Key；
- 不产生供应商费用；
- 收集 Integration Tests，但保持显式 skip。

PostgreSQL 与真实 LLM 测试拥有不同开关，启用其中一个不得隐式启用另一个。

## Runtime 与 Compose 质量门禁

默认测试还会离线验证：

- Python 项目和容器 Runtime 仅允许 3.13；
- 供应商 SDK、自动 retry、自动 Provider routing 和静默 fallback 不得进入依赖边界；
- 环境模板、Dockerfile、Compose、文档和测试不包含真实秘密形状；
- Dockerfile 与 Compose 保持镜像、Migration、Backend 和 readiness 职责分离；
- Phase 3–6 的 Persistence、Provider、LLMService 和无状态 Chat API 依赖方向无回归；
- README、Runtime、Environment 及 Integration 文档与当前实际验证状态一致。

这些测试只读取项目文件并检查 AST、TOML 和 YAML，不调用 Docker CLI 或 daemon。Docker
动态 build/run 与端点 Smoke Test 必须单独执行并单独记录，不能由静态测试结果代替。

## Phase 8 Conversation 质量门禁

Phase 8 Step 6 在既有 Domain、Application、Persistence 与 API 测试之上增加集中回归门禁：

- 逐层验证 Domain、Application、Persistence Adapter、HTTP Adapter 与 Provider 的依赖方向；
- 固化 `/health`、`/ready`、`/version`、无状态 Chat Completions 和六个 Conversation
  endpoint 的公开路由表面；
- 明确拒绝向既有 `ChatRequest` 注入 `conversation_id`；
- 禁止 Conversation 边界泄漏 Provider 原始对象、传输细节、凭据或持久化 SSE；
- 收集 PostgreSQL-backed Conversation API production-wiring test，但默认保持 skip。

这些测试不修改 API 契约，不需要真实 API Key，不调用真实 Provider，也不产生费用。

## 环境契约门禁

Runtime Contract Tests 会验证四份受版本控制模板：

- 覆盖全部 `Settings` 和 `LLMSettings` 字段；
- 默认选择 `mock`；
- 真实 Provider 字段为空；
- local/docker/test/production 专属键不串层；
- 生产样例在数据库秘密未注入时 fail closed；
- Dockerfile 和 Compose 不包含供应商密钥；
- Git 和 Docker build context 排除真实环境文件。
