# 开发与架构规范

## 适用范围

本规范适用于 Phase 5 Freeze 之后以及 Phase 6 Adapter 冻结基线之上的所有后端开发。
Phase 6 已正式冻结，Git 基线为 `v0.6.0`；Phase 7 已通过 Release Gate 并以 `v0.7.0`
冻结。Phase 8 当前进行 Conversation Testing Strategy / Quality Gate Hardening，尚未
Freeze。关键词“必须”“不得”表示架构门禁，不能以开发便利或供应商兼容为由绕过。

## 基本原则

- 每个阶段结束时项目必须保持 Runnable、Testable 和 Extensible。
- 上层模块依赖抽象和稳定入口，不依赖基础设施具体实现。
- 新功能优先通过新增模块扩展，不修改已冻结公共契约。
- 配置遵循 12-Factor App，从环境变量或 `.env` 注入，不写死部署信息。
- 代码必须具备完整类型标注，并保持模块职责单一。
- 不为尚未进入范围的业务提前建立模型、接口或集成。

## 模块依赖规则

允许的核心依赖方向为：

```text
HTTP Client -> Chat Router -> ChatService -> LLMService -> LLMProvider Interface
未来 API / 业务模块 -> Repository 契约 -> Repository 实现 -> SQLAlchemy
Bootstrap -> Settings + Registry + Factory + Provider + LLMService
```

强制约束：

- `app/llm` 不得导入 `app.db`、`app.models`、`app.repositories` 或 SQLAlchemy。
- LLM Provider 不得依赖 FastAPI、Redis 或业务模块。
- `app/llm/http` 不得依赖具体 Provider、Chat、API、Persistence 或业务 Service。
- 业务模块不得导入具体 Provider、Registry 或 Factory。
- `LLMService` 不得读取环境变量，也不得定位或创建 Provider。
- Factory 只能通过 Registry 创建 Provider，不得包含供应商分支。
- Bootstrap 是 LLM 层唯一组合根；Registry 和 Provider 不得保存为全局可变单例。
- Persistence Layer 不得依赖 LLM Provider Layer。
- Chat Router 只能通过 Dependency 获取 `ChatService`，不得调用 `LLMService`、具体
  Provider、Registry、Factory 或 Bootstrap。
- `ChatService` 只能依赖注入的 `LLMService`、冻结的 LLM DTO 与独立 Chat DTO；不得
  依赖 FastAPI、Provider 实现、数据库、Repository、SQLAlchemy 或 Redis。
- Chat API 不得加入数据库 Dependency，不得在请求路径读取或写入 Persistence Layer。
- LLM 生命周期只在 FastAPI Lifespan 组装，Dependency 不读取环境变量或执行 Bootstrap。

可使用自动化依赖扫描或架构测试加强上述约束，但工具不能替代 Code Review。

## Chat API 标准

- `POST /api/v1/chat/completions` 保持无状态；`messages` 只代表客户端随本次请求提交的
  临时上下文，服务端不得保存或补建聊天历史。
- `request_id` 只关联单次调用，不得作为 `conversation_id`、用户标识、认证凭据或
  数据库主键使用。缺失时由 ChatService 为本次调用生成。
- 客户端只允许提交 `user` 与 `assistant` role；系统策略应由未来服务端编排层注入，
  不得通过在当前公共 Schema 开放 `system` role 绕过边界。
- HTTP Chat DTO 与 LLM DTO 必须分别维护。不得直接返回 `LLMResponse`、
  `LLMStreamChunk`、`provider_request_id`、SDK usage 或供应商原始错误。
- 公共 Schema 必须拒绝未知字段；不得加入 `extra_kwargs`、vendor options、tools、
  functions 或其他绕过契约的逃生口。
- 未来有状态聊天必须新增 Conversation Service、Repository Protocol 和新接口；不得
  修改当前无状态 completions 的路径、字段或语义。

## SSE 标准

- Chat 流式响应使用 `text/event-stream`，不用 WebSocket；事件只允许冻结的 `chunk`、
  `done` 和 `error` 契约。
- Router 应预取首个事件，使响应开始前的 LLM 错误仍能使用正常 HTTP 状态和统一错误体。
- 响应开始后的错误只能发送安全 `error` SSE Event，然后关闭流，不得泄漏异常字符串。
- 一个流内的 `request_id` 必须稳定，事件顺序必须由 `sequence` 明确表达；空文本响应
  仍必须产生 `done`。
- 下游取消和断开必须传播，不得吞掉 `asyncio.CancelledError`；ChatService 与 Router
  都必须在正常、错误和取消路径关闭各自持有的异步迭代器。
- 不得为了 SSE 缓存完整 Prompt、完整生成结果或完整 Chunk 序列，也不得记录 Chunk 正文。

## HTTP 错误边界

- 预期 LLM 失败必须集中映射为现有 `ApplicationError`，不得在 Router 中散落未经规范化
  的 `HTTPException`。
- 客户端消息必须使用固定公共错误码和安全文案，不能使用 `str(exception)`、异常
  `cause`、供应商 HTTP 错误或 SDK Exception。
- 安全 details 只允许最小关联信息，例如客户端提供的 `request_id` 和经过验证的
  `retry_after_seconds`。
- 响应不得包含 API Key、Authorization Header、完整 Prompt、完整模型响应或
  `provider_request_id`。未知异常继续交由既有全局 500 Handler 处理。
- 请求校验继续使用既有 422 错误结构；系统端点的错误语义不得因 Chat 映射改变。

## Provider Adapter 标准

每个新增 Adapter 必须：

1. 实现 `LLMProvider` 的完整生成、流式生成和关闭契约。
2. 把供应商 HTTP/SSE 请求和响应映射到公共 Schema，不暴露传输或供应商类型。
3. 把供应商、HTTP 和协议异常映射为统一 `LLMException`。
4. 传播取消，不吞掉 `asyncio.CancelledError`。
5. 在流结束、异常和取消路径释放客户端、响应流及其他资源。
6. 只通过构造参数接收已经校验的配置，不自行读取环境变量。
7. 复用内部 `LLMHTTPClient` 与 SSE Parser，不复制通用传输实现。
8. 不安装或导入供应商 SDK；确有必要时必须先进行独立架构与安全评审。
9. 在 Bootstrap 中显式注册，并加入同一默认 Contract Tests。
10. 为供应商 JSON、异常、流取消和资源释放提供独立 MockTransport 测试。

新增 Provider 不得要求修改 `LLMService`、Factory、未来 Chat API 或 Persistence
Layer。若无法满足，说明公共契约可能需要演进，必须先发起独立架构评审。

## 配置与密钥

- 版本控制只保存 `.env.example`、`.env.docker.example`、`.env.test.example` 和
  `.env.production.example`，不得提交真实 `.env` 或密钥。
- local、docker、test 和 production sample 必须保持场景隔离，不能依赖未声明的模板
  覆盖顺序。
- 所有模板默认使用 `LLM_PROVIDER=mock`；生产样例在数据库秘密未注入时必须 fail closed。
- API Key、Token、密码使用 `SecretStr` 或等价安全类型。
- 缺失、非法或未注册配置必须 fail fast，不得自动回退。
- 真实 Provider Base URL 必须来自环境、使用 HTTPS，且不得包含 userinfo、query 或
  fragment。
- connect/read/stream timeout 留空时继承 `LLM_TIMEOUT_SECONDS`；stream timeout 只表示
  相邻事件空闲上限，不表示整个流总时长。
- 配置层只负责读取、规范化、校验和保护值，不负责创建 Provider。
- Registry 是 Provider 名称是否可用的最终权威。
- 新增配置键必须同步更新所有适用的环境模板、专题文档和配置契约测试。
- 真实秘密只能由当前进程、CI Secret 或部署平台 Secret Manager 注入，不得进入
  Dockerfile、Compose 默认值、示例模板正文或文档。
- 配置对象的 `repr`、日志和错误消息不得泄漏密钥。

## 日志与隐私

以下内容不得写入日志、trace attribute、异常消息或测试快照：

- API Key、Token、Authorization Header 或 Cookie；
- 完整 Prompt、系统提示词或消息正文；
- 完整模型响应；
- 原始 SDK Request/Response/Event；
- 可能包含个人数据或家庭设备敏感信息的载荷。
- 原始 `httpx.Request/Response`、供应商 JSON 或异常 cause。

未来可记录经过批准的最小元数据，例如 Provider 名称、模型名、耗时、标准错误码、
token 数量和不可逆关联标识。引入 prompt/response 采样必须经过单独隐私与安全评审。

## 测试标准

默认测试命令：

```bash
cd backend
python -m pytest
```

默认测试必须：

- 零外部网络；
- 零真实 API Key；
- 零供应商账号依赖；
- 使用 Mock Provider 或离线传输替身；
- 覆盖完整生成、流式生成、错误映射、取消和关闭；
- 验证 Schema 拒绝供应商字段和原始 SDK 对象；
- 验证未注册 Provider 明确失败且不回退；
- 保持现有系统端点和 Persistence 测试无回归。
- 覆盖 Chat Schema、DTO 转换、生命周期、依赖注入、JSON/SSE、错误映射和流取消；
- 通过 AST 或等价扫描验证 Router、ChatService、Provider 和 Persistence 的依赖方向；
- 验证 Chat API 无数据库访问、无 Redis、无会话状态且不需要 API Key。

真实 PostgreSQL 测试继续使用既有 `--run-integration` 显式开关。

Conversation Persistence 必须遵守以下边界：

- Application 层只依赖纯 Python Repository/Unit of Work Protocol，不导入 SQLAlchemy；
- SQLAlchemy Adapter 集中完成 Domain Entity 与 ORM Model 转换，不向上层返回 ORM；
- Repository 方法只允许 `flush`，不得自行 `commit`；
- 单个事务的 `commit`、`rollback` 和异常清理只能由 Conversation Unit of Work 控制；
- Conversation 行锁必须通过显式 `get_for_update` 边界获取，不依赖隐式 ORM cascade；
- Message Context 查询只返回已完成 Turn 的有界消息，不读取未完成 Chunk 或 Provider 原始载荷。

真实 LLM 测试只能位于 `tests/integration/llm/`，必须具有 `llm_integration` marker，
并同时要求：

- `--run-llm-integration`；
- 当前进程环境 `LLM_INTEGRATION_ACKNOWLEDGE_COST=true`；
- 目标 Provider 的 API Key、HTTPS Base URL 和默认模型。

缺少条件时必须 skip，不得 fail 或 fallback。`--run-integration` 与
`--run-llm-integration` 不互相启用。默认 CI 不得注入真实密钥或成本确认。真实测试只
允许最小非流式/流式调用，不使用额度验证认证、限流或畸形响应。

新增 Provider 必须通过公共 Contract Tests，并添加 Adapter 自身的映射、异常和资源
释放测试。公共契约测试应验证可观察行为，供应商专属分块或协议细节只能在 Adapter
测试中断言。

## Docker Compose 标准

- 基础本地拓扑固定包含 `postgres`、`redis`、`migration` 和 `backend`；
- PostgreSQL 必须先通过自身 healthcheck，Migration 才可执行；
- Migration 必须使用 Backend 的同一镜像一次性执行 `alembic upgrade head`，失败时
  Backend 不得启动；
- Backend 启动命令不得执行 Migration 或 pytest；
- Backend 容器 healthcheck 使用 `/health`，应用 `/ready` 继续只表达 PostgreSQL
  readiness；
- Redis 仅保留自身 healthcheck，不得成为 Backend 依赖或 `/ready` 条件；
- Docker 开发配置必须从 `.env.docker` 注入，并默认使用 `mock` Provider；
- Compose 不得包含 API Key、Authorization Header、真实 Provider 默认值或生产秘密；
- 开发 override 不得被生产样例隐式继承，生产样例不得包含 bind mount 或 reload；
- 默认测试只做静态 Compose 契约验证，不得依赖 Docker daemon。

Runtime 质量门禁必须同时验证 Python 版本范围、SDK 禁入、秘密形状、Integration opt-in、
默认网络阻断、冻结层依赖方向和文档事实一致性。门禁不得执行 Docker、真实数据库或真实
LLM，也不得把未运行的 Integration Tests 或动态容器验证描述为通过。

默认 GitHub Actions CI 只允许由 `push` 和 `pull_request` 触发，使用 `contents: read`
最小权限和 Python 3.13。其唯一测试入口为默认 `python -m pytest`；不得读取 GitHub
secrets、传入 Integration 开关、启动 Compose 或启用真实 Provider。依赖安装网络与测试
执行网络必须分开描述，测试执行仍由项目 Network Gate 保持离线。

PostgreSQL Integration Workflow 不得响应 pull request，必须使用临时 PostgreSQL 17 和
CI 专属凭据，且只能启用 `--run-integration`。真实 LLM Workflow 必须仅限手动触发，绑定
protected environment、人工成本确认和单一 Provider 配置，只启用
`--run-llm-integration`。两类 Workflow 不得共享 Integration 开关、Provider secrets 或
自动 fallback/retry/routing 行为。

## Release Gate 标准

- 发布证据只允许使用 `Passed`、`Skipped`、`Not Run` 和 `Failed` 四种状态；只有实际执行
  成功的检查可记为 `Passed`。
- 静态 Dockerfile/Compose 契约不能替代镜像 build/run、非 root 身份、Migration、Compose
  up 和系统端点 Smoke Test 的动态证据。
- Workflow 文件和 Contract Tests 通过不能替代 GitHub Runner 的真实 run 记录。
- 默认 CI、PostgreSQL Integration 和 Manual LLM Integration 必须分别记录，不能互相
  代替或共享授权。
- 任一 Phase 7 硬门禁为 `Skipped`、`Not Run` 或 `Failed` 时只能标记 `Freeze Pending`，
  不得创建、移动或发布 `v0.7.0`。
- Tag 只能建立在全部硬门禁通过、文档与实现一致且工作树 clean 的审核 commit 上。
- 当前状态与人工检查清单以 [Phase 7 Release Gate](../operations/release-gate.md) 为准。

## 变更质量门禁

每次影响 LLM Provider Layer 或 Chat API Layer 的变更至少检查：

1. 默认 `python -m pytest` 通过。
2. 不存在未批准的供应商 SDK 或网络请求。
3. Mock 模式在无密钥环境可创建并离线运行。
4. 供应商异常和 SDK 对象没有越过 Adapter 边界。
5. Factory 没有新增供应商条件分支。
6. Bootstrap 注册显式、Registry 在组合后冻结。
7. 密钥、完整 Prompt 和完整响应没有进入日志或异常。
8. Persistence Layer、Alembic、Docker 启动链和 readiness 没有被破坏。
9. README、四类环境模板和专题文档与实现一致。
10. 临时测试文件、缓存和构建产物没有提交。
11. Chat Router 只通过 Dependency 调用 ChatService，且 ChatService 只调用 LLMService。
12. 非流式 JSON、SSE chunk/done/error、错误状态码和取消释放契约无回归。
13. Chat 路径没有数据库或 Redis Dependency，没有保存消息、完整响应或会话状态。
14. `/health`、`/ready`、`/version` 路径和既有语义无回归。
15. 架构依赖扫描、API Contract Tests 和全量默认测试均通过。
16. HTTP Client 保持 `trust_env=False`，没有全局 Client 或导入时网络行为。
17. 真实 LLM 测试保持独立 marker、显式开关、成本确认和安全 skip reason。
18. 测试报告没有密钥、Authorization、完整 Prompt、Response 或 Chunk。

## 必须进行架构评审的变更

以下变更不得作为普通 Adapter 开发直接合入：

- 修改 `LLMProvider` 方法或生命周期；
- 修改公共 Request、Response、Chunk、finish reason 或异常语义；
- 在 `LLMService` 中加入业务状态、持久化、缓存、权限或供应商选择；
- 改变 Registry、Factory 或 Bootstrap 的职责边界；
- 增加自动回退、自动降级、多 Provider 路由或重试编排；
- 记录 Prompt、响应正文或供应商原始载荷；
- 让 LLM 成为 `/ready` 的必需依赖；
- 建立 LLM 与 Persistence Layer 的直接依赖；
- 修改 Phase 3 或 Phase 4 Freeze 基线。
- 修改 `/api/v1/chat/completions` 的路径、无状态语义或公开请求/响应字段；
- 新增、删除或改变 `chunk`、`done`、`error` SSE Event 的语义；
- 让 Router 绕过 ChatService，或让 ChatService 定位 Provider/基础设施；
- 在当前 Chat API 中加入 `conversation_id`、聊天历史、认证、持久化或 Redis；
- 改变 LLMException 的公共 HTTP 状态码、错误码或安全披露策略；
- 让 LLM 远程可用性成为 `/ready` 的必需条件；
- 修改 Phase 5 Freeze 基线。
- 引入供应商 SDK、系统代理继承或新的通用 HTTP Client。
- 修改 timeout 语义或允许客户端覆盖 Provider Base URL。
- 改变真实 LLM integration 的显式成本确认和网络门禁。

## Freeze 规则

Phase 3、Phase 4、Phase 5、Phase 6 与 Phase 7 已冻结。Phase 7 的 Docker 动态验证、
GitHub Runner 与审批路径证据已齐，annotated tag `v0.7.0` 不得移动、删除或重建。后续阶段
不得用 Runtime、CI 或 Release 工作绕过既有冻结边界；对 Phase 3–7 只允许兼容性扩展：

- 新增 Provider Adapter，并在 Bootstrap 显式注册；
- 新增调用 `LLMService` 的上层模块；
- 新增调用稳定 Chat API 的客户端，或在现有无状态端点之上新增上层服务；
- 通过新增 Conversation Service、Repository Protocol 和新接口实现有状态聊天；
- 新增不破坏公共契约的测试、文档和观测装饰器；
- 经独立架构评审后进行版本化契约演进。

详细 Freeze 基线见 [LLM Provider Layer](../architecture/llm-provider-layer.md)、
[Chat API Layer](../architecture/chat-api-layer.md)、[架构总览](../architecture/overview.md)、
[LLM Provider 运维指南](../operations/llm-providers.md) 和
[LLM Integration 测试指南](../testing/llm-integration.md)。Phase 7 的证据状态、Tag 与回滚
规则见 [Phase 7 Release Gate](../operations/release-gate.md)。
