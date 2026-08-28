# LLM Provider 运维指南

## 适用范围

本文说明 Phase 6 已实现的 `mock`、DeepSeek 和 OpenAI Provider 如何配置、部署和安全
运维。它不改变 Phase 4 的公共 Provider 契约，也不改变 Phase 5 Chat API。

Phase 6 当前状态是 **Freeze Pending / 待正式 pytest 验证**。生产启用真实 Provider 前，
必须先在项目 Python 3.13 环境完成默认全量测试，并在受控环境完成目标 Provider 的显式
Integration Tests。

## Provider 选择

Bootstrap 只进行显式注册和确定性选择：

```text
LLM_PROVIDER=mock      -> MockProvider
LLM_PROVIDER=deepseek  -> DeepSeekProvider
LLM_PROVIDER=openai    -> OpenAIProvider
```

不存在自动 fallback、自动路由、自动重试或自动降级。选中 Provider 配置失败时，应用
启动会明确失败，不会切换到 `mock`。切换 Provider 是部署配置变更，必须由操作者明确
执行并经过测试，而不是运行时容错策略。

## 配置参考

### 通用配置

| 变量 | 说明 |
| --- | --- |
| `LLM_PROVIDER` | 当前选择的 Provider；规范化为小写 |
| `LLM_DEFAULT_MODEL` | 供应商无关的既有默认模型配置，保留原语义 |
| `LLM_TIMEOUT_SECONDS` | 所有细分 timeout 的继承基线，必须为正数 |
| `LLM_CONNECT_TIMEOUT_SECONDS` | 建立 TCP/TLS 连接的时间上限 |
| `LLM_READ_TIMEOUT_SECONDS` | 非流式响应读取的时间上限 |
| `LLM_STREAM_TIMEOUT_SECONDS` | 相邻流式事件之间的空闲上限，不是整个流总时长 |
| `LLM_DEFAULT_TEMPERATURE` | 默认生成温度，范围 `0..2` |
| `LLM_DEFAULT_MAX_TOKENS` | 默认最大生成 token 数，必须为正整数 |

三个细分 timeout 留空时分别继承 `LLM_TIMEOUT_SECONDS`。它们不得设置为零、负数、
NaN 或无穷值。应用层的请求取消仍独立于 timeout，并必须传播到 Provider。

### DeepSeek

选择 `LLM_PROVIDER=deepseek` 时必须提供：

- `DEEPSEEK_API_KEY`；
- `DEEPSEEK_BASE_URL`；
- `DEEPSEEK_DEFAULT_MODEL`。

### OpenAI

选择 `LLM_PROVIDER=openai` 时必须提供：

- `OPENAI_API_KEY`；
- `OPENAI_BASE_URL`；
- `OPENAI_DEFAULT_MODEL`。

非选中 Provider 的配置可以为空。`LLM_PROVIDER=mock` 不要求任何真实供应商配置。

## Base URL 规则

Base URL 必须来自部署环境，不得写死在源码、镜像或文档示例中，并满足：

- 使用 HTTPS；
- 不包含 username/password userinfo；
- 不包含 query string；
- 不包含 fragment；
- 尾部斜杠由 Settings 统一规范化。

Adapter 在规范化 Base URL 后追加受控的 Chat Completions 相对路径。不得允许客户端通过
Chat Request 覆盖 Base URL，也不得引入 `provider_options` 或 `extra_kwargs` 逃生口。

## 密钥管理

- API Key 只通过环境或部署平台 Secret 注入；
- 不提交 `.env`，版本控制中只保留空值 `.env.example`；
- 不在终端命令参数、Shell history、Dockerfile、Compose 文件或镜像层写入密钥；
- Settings 使用 `SecretStr` 保护常规 `str`/`repr`，但这不构成记录许可；
- 日志、异常、trace、metrics label 和测试报告不得包含 API Key 或 Authorization Header；
- 密钥轮换应通过受控部署完成，旧密钥撤销后再验证最小调用。

## HTTP 与 SSE 运行边界

真实 Adapter 共享内部 `LLMHTTPClient` 和协议级 SSE Parser：

- HTTP Client 使用 `httpx.AsyncClient`，`trust_env=False`，不继承系统代理；
- 不安装 OpenAI、DeepSeek 或其他供应商 SDK；
- SSE Parser 只处理 frame、`data:`、comment、空行和 `[DONE]`；
- 供应商 JSON 仅由对应 Adapter 解释；
- 完整响应和流式 Chunk 不缓存、不写日志；
- 取消、异常或生命周期关闭时必须释放响应流与 Client；
- `aclose()` 必须可重复调用。

如部署环境强制要求代理，应先进行单独安全与架构评审，不得依赖未审计的系统代理变量。

## 日志与观测

允许记录的最小元数据包括经过评审的 request ID、Provider 名称、模型名、耗时、标准
finish reason、token usage 和公共错误码。禁止记录：

- API Key、Authorization Header、Cookie；
- 完整 Prompt、消息正文或 system instruction；
- 完整生成响应或 Chunk delta；
- 原始供应商 Request/Response/SSE JSON；
- `httpx` 原始异常、异常 cause 或可能携带 Header 的对象。

Provider 必须把 HTTP、协议和供应商错误转换为统一 `LLMException`，Chat 边界再映射为
固定、安全的 HTTP/SSE 错误。

## Readiness 与故障处理

`/health`、`/ready`、`/version` 保持 Phase 3/5 语义：`/ready` 只验证应用与
PostgreSQL，不发起 LLM 请求。原因是远程模型可用性、配额和延迟不应使应用基础
readiness 抖动，也不能通过健康检查持续消耗额度。

遇到供应商错误时：

1. 根据统一公共错误码区分配置、认证、限流、超时、不可用和无效响应；
2. 在供应商控制台或受控日志系统核查，不向客户端返回原始诊断；
3. 明确决定是否修复配置、暂停真实 Provider 或部署切换；
4. 不在请求内自动重试或切换 Provider；
5. 变更后先运行默认离线测试，再显式运行目标 Provider 最小 Integration Tests。

## 成本与配额

- 默认开发和 CI 使用 `mock`；
- 默认 pytest 通过 Socket/DNS 门禁阻止真实网络；
- 真实 Integration Tests 只发送最小 `Say hi.` 请求并限制为 16 tokens；
- 必须同时提供 `--run-llm-integration` 和
  `LLM_INTEGRATION_ACKNOWLEDGE_COST=true`；
- 不使用真实额度测试认证失败、限流、超时或畸形响应，这些场景由 MockTransport 覆盖；
- Phase 6 尚未实现预算、成本统计、配额治理或按用户计费。

详细测试命令和 skip 规则见 [LLM Integration 测试指南](../testing/llm-integration.md)。

## 上线检查清单

1. 使用 Python 3.13 安装锁定范围内的项目依赖。
2. 默认 `python -m pytest` 全量通过。
3. 目标 Provider 的 Base URL、模型和密钥由部署 Secret 注入。
4. 非目标 Provider 的密钥保持为空或不注入。
5. 确认日志、trace 和错误采集不记录敏感载荷。
6. 显式确认成本并执行目标 Provider 最小 Integration Tests。
7. 验证非流式和流式调用后 Client 均正确关闭。
8. 验证 Chat API 公共 JSON/SSE 契约没有因 Provider 改变。
9. 验证 `/ready` 仍只表达应用与 PostgreSQL readiness。
10. 记录部署选择和回滚步骤，但不得记录密钥。

