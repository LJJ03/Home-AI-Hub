# LLM Integration 测试指南

## 当前验证状态

Phase 6 已在项目 Python 3.13 环境完成默认全量 pytest，并正式 Freeze。DeepSeek/OpenAI
真实 Integration Tests 尚未运行，仍需要明确授权、成本确认和完整 Provider 配置；未运行
不得描述为通过或线上验证完成。

## 三类测试完全隔离

### 默认离线测试

```bash
cd backend
python -m pytest
```

默认测试：

- 不需要 PostgreSQL；
- 不需要真实 API Key、Base URL、模型或供应商账号；
- 使用 Mock Provider 和 `httpx.MockTransport`；
- 通过自动 fixture 阻断 DNS 与原始 Socket 连接；
- 收集真实 LLM 测试但将其标记为 skip；
- 不产生供应商费用。

这是每次提交和默认 CI 必须运行的测试路径。

`.env.test.example` 始终使用 `mock` 且将成本确认保持为关闭。真实 Provider 的 API Key、
HTTPS Base URL 和默认模型只能通过当前进程或受控 Secret 注入，不能填入受版本控制模板。

### PostgreSQL integration

```bash
cd backend
python -m pytest --run-integration
```

`--run-integration` 只启用 Phase 3 PostgreSQL、Alembic 和 Repository 集成测试，不会
启用真实 LLM 测试。数据库测试使用独立临时数据库，并沿用既有清理流程。

### 真实 LLM integration

POSIX Shell：

```bash
cd backend
LLM_INTEGRATION_ACKNOWLEDGE_COST=true python -m pytest --run-llm-integration
```

Windows PowerShell：

```powershell
cd backend
$env:LLM_INTEGRATION_ACKNOWLEDGE_COST = "true"
python -m pytest --run-llm-integration
```

不要把 API Key 写在命令中。应提前通过当前进程环境或受控 Secret 注入目标 Provider 的
配置。`--run-llm-integration` 不会启用 PostgreSQL integration。

### GitHub Actions 手动 Workflow

`.github/workflows/llm-integration.yml` 只能通过 `workflow_dispatch` 手动触发，不响应
push、pull request、fork pull request 或 schedule。操作者必须：

1. 从 `provider` choice 中明确选择 `deepseek` 或 `openai`；
2. 将布尔输入 `acknowledge_cost` 明确设为 `true`；
3. 通过名为 `llm-integration` 的 GitHub protected environment 完成人工审批。

仓库管理员应在该 protected environment 中配置 required reviewers，并分别配置：

- Secret：`DEEPSEEK_API_KEY` 或 `OPENAI_API_KEY`；
- Variable：对应的 `DEEPSEEK_BASE_URL` / `OPENAI_BASE_URL`；
- Variable：对应的 `DEEPSEEK_DEFAULT_MODEL` / `OPENAI_DEFAULT_MODEL`。

每次运行只进入被选 Provider 的专属 job，只向该 job 注入对应配置，不要求另一 Provider
的 Secret。成本未确认或配置缺失时会在测试前 fail closed；不会回退到 Mock、自动切换
Provider 或自动 retry。测试命令仅为：

```console
python -m pytest --run-llm-integration
```

Workflow 不传入 `--run-integration`，不打印 Secret、Authorization Header、Prompt、完整
Response、完整 Chunk 或供应商错误体。该 Workflow 已定义但真实测试仍未运行，也未产生
费用；未运行不得描述为通过。

## 运行前置条件

每一个真实 LLM 测试必须具有 `llm_integration` marker，并且以下全局条件同时满足：

1. 显式传入 `--run-llm-integration`；
2. 当前进程环境中 `LLM_INTEGRATION_ACKNOWLEDGE_COST=true`。

DeepSeek 还需要：

- `DEEPSEEK_API_KEY`；
- `DEEPSEEK_BASE_URL`；
- `DEEPSEEK_DEFAULT_MODEL`。

OpenAI 还需要：

- `OPENAI_API_KEY`；
- `OPENAI_BASE_URL`；
- `OPENAI_DEFAULT_MODEL`。

缺少 CLI 开关、成本确认或目标 Provider 任一配置时，测试会给出只包含缺失条件名称的
skip reason。只配置 DeepSeek 时 OpenAI 测试会跳过，反之亦然；测试不会回退到 Mock，
也不会要求非选中 Provider 的密钥。

`.env.example` 中的 `LLM_INTEGRATION_ACKNOWLEDGE_COST=false` 只是安全模板。测试门禁读取
当前进程环境，必须由操作者在本次明确运行前主动设为 `true`。

## 真实测试覆盖

每个真实 Provider 只执行两个最小测试：

1. `generate()` 非流式最小调用；
2. `stream_generate()` 流式最小调用。

测试直接实例化对应 Provider，避免把 Provider 验证与 Chat API、Lifespan、数据库或
业务层混合。测试使用无敏感内容的 `Say hi.`，最大生成量为 16 tokens，并验证：

- `provider_name` 正确；
- `model_name` 非空；
- finish reason 满足冻结枚举；
- 非流式文本为空或非空白；
- 流式至少收到 final chunk；
- Chunk 可以按顺序重组，但不会被打印；
- 内部 `provider_request_id` 不进入公开 `ChatResponse`；
- Provider 和流迭代器在正常、异常、取消路径关闭；
- 单个操作具有受控超时。

真实测试不覆盖认证失败、限流、超时、网络失败或畸形 JSON，以避免无意义消耗额度。
这些错误通过离线 MockTransport 测试覆盖。

## 网络门禁

默认 autouse fixture 拦截：

- DNS 解析；
- `socket.create_connection`；
- 原始 `socket.connect` / `connect_ex`。

只有以下测试可以绕过网络阻断：

- 带 `integration` marker 且显式传入 `--run-integration` 的 PostgreSQL 测试；
- 带 `llm_integration` marker、显式传入 `--run-llm-integration` 且成本确认为 `true`
  的真实 LLM 测试。

普通测试即使传入某个 integration 开关也不能联网。LLM 和 PostgreSQL 开关不互相
授权。`httpx.MockTransport` 不使用真实 Socket，因此默认离线 Provider 测试不受影响。

内部 HTTP Client 固定 `trust_env=False`，不读取系统代理。测试与生产 Adapter 均不得
绕过这一边界。

## 安全输出规则

真实测试不得输出或写入测试失败消息：

- API Key 或 Authorization Header；
- 完整 Prompt 或消息列表；
- 完整非流式 Response；
- 完整流式 Chunk 或重组文本；
- 原始 `httpx.Request` / `httpx.Response`；
- 供应商原始异常或异常 cause。

测试只断言规范化元数据和布尔状态。密钥不硬编码，不写入 fixture ID、参数 ID、日志或
snapshot。失败必须通过统一安全异常边界呈现。

## CI 规则

- 默认 CI 只能执行 `python -m pytest`；
- 不向默认 CI 注入真实 Provider 密钥；
- 不在默认 CI 设置成本确认；
- PostgreSQL integration 由独立 workflow 执行，不响应 pull request；
- 真实 LLM integration 由仅限手动触发、受 protected environment 保护的独立 workflow
  执行；
- 真实测试任务不得因失败自动切换 Provider 或重试；
- 测试报告和构建日志必须经过敏感信息审查。

## Phase 6 Freeze 状态

Phase 6 Freeze Git 基线为 `v0.6.0`。默认测试的通过不代表真实 Provider Integration 已
运行。真实 LLM Integration 仍要求独立授权和成本确认；如果未来成为生产上线门禁，必须
分别记录目标 Provider、执行时间和通过/失败/未运行状态，但不得记录响应正文或凭据。
