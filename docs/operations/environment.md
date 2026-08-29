# 环境变量分层与安全边界

## 目标

环境配置遵循 12-Factor 原则：同一应用镜像通过运行时环境变量适配不同环境，源码、镜像、
Compose 默认值和受版本控制文档均不保存真实秘密。Pydantic Settings 负责类型校验、
规范化和 fail-fast，不负责创建数据库或 Provider。

进程环境变量优先于 dotenv 文件。生产部署应由 Secret Manager 或编排平台注入环境变量，
不应把示例文件作为秘密存储方案。

## 配置文件矩阵

| 模板 | 场景 | 数据库地址边界 | LLM 默认值 | 专属配置 |
|---|---|---|---|---|
| `.env.example` | 宿主机本地开发 | loopback PostgreSQL | `mock` | 无 Compose/Test 键 |
| `.env.docker.example` | Docker 本地开发 | Compose 服务名 `postgres` | `mock` | PostgreSQL、Docker URL、Redis 端口 |
| `.env.test.example` | 默认测试与 PostgreSQL Integration | loopback PostgreSQL 17 | `mock` | 测试 PostgreSQL；成本确认固定关闭 |
| `.env.production.example` | 生产部署契约样例 | 留空，必须由部署平台注入 | `mock` | 无 Compose/Test 键 |

四份模板互不隐式继承。使用者应选择与当前场景一致的模板，不应合并多个模板后猜测覆盖
顺序。

## 配置所有权

### 应用运行配置

`Settings` 管理：

- `APP_NAME`、`APP_VERSION`、`APP_ENVIRONMENT`；
- `APP_HOST`、`APP_PORT`、`APP_LOG_LEVEL`；
- `DATABASE_URL`、`SQLALCHEMY_ECHO`；
- `POOL_SIZE`、`MAX_OVERFLOW`；
- `DATABASE_HEALTHCHECK_TIMEOUT_SECONDS`。

`DATABASE_URL` 必须使用 `postgresql+asyncpg` scheme。生产样例故意将其留空，因此未经
秘密注入直接启动必须失败。

### LLM 配置

`LLMSettings` 管理：

- Provider、默认模型、温度和 token 上限；
- 通用、连接、读取和流式空闲 timeout；
- OpenAI 和 DeepSeek 各自的 API Key、HTTPS Base URL 与默认模型。

所有模板默认选择 `mock`，未选中 Provider 的字段保持空白。选择 OpenAI 或 DeepSeek
时，API Key、HTTPS Base URL 和默认模型缺少任一项都会 fail fast，不会回退到 `mock`。

连接、读取和流式 timeout 留空时继承通用 timeout。流式 timeout 表示相邻事件之间的
最大空闲时间，不是整个生成过程的总时长。

### Compose 专属配置

PostgreSQL 容器初始化配置、`DOCKER_DATABASE_URL` 和 Redis 暴露端口只属于 Docker
开发模板。它们不是应用公共 Settings，也不应出现在生产样例中。Redis 当前只启动容器，
不参与应用逻辑或 `/ready`。

### 测试门禁

`LLM_INTEGRATION_ACKNOWLEDGE_COST` 只属于测试进程，不属于应用配置。测试模板固定为
`false`。真实 LLM Integration 仍必须同时显式传入 pytest 开关和当前进程成本确认；
编辑示例文件不能绕过该门禁。

## 使用方式

本地开发将 `.env.example` 复制为未受版本控制的 `.env`，随后替换本地数据库凭据。
Docker 开发将 `.env.docker.example` 复制为 `.env.docker`。测试模板可复制为 `.env.test`
以配置独立 PostgreSQL 17 测试服务；默认 pytest 本身不要求复制该文件。

复制模板前必须确认 `.env` 不存在；已有配置应逐项合并，不能通过复制命令覆盖现有秘密。

基础 Compose 为 Backend 和 Migration 显式声明 `env_file: .env.docker`。启动命令还必须
使用 `docker compose --env-file .env.docker ...`，使 PostgreSQL 初始化值、端口以及
`DOCKER_DATABASE_URL` 的 Compose 插值来自同一文件。Compose 将
`DOCKER_DATABASE_URL` 注入容器内的标准 `DATABASE_URL`，应用 Settings 因此不需要知道
Docker 专属字段。不要省略 `--env-file`，也不要把 Docker 模板复制为 `.env`；否则宿主机
进程环境或本地开发 `.env` 可能参与插值，形成配置来源不一致。

测试拓扑使用 `.env.test.example` 的隔离数据库名和 `5433` 宿主机端口；生产 Compose
样例不读取 `.env.production.example`，其镜像和数据库连接必须由部署平台显式注入。

生产环境不得从工作目录加载带真实值的 dotenv 文件。应由部署平台分别注入数据库秘密和
所选 Provider 秘密，并保留配置校验失败即停止启动的语义。

默认 pytest 通过 monkeypatch、显式 Test Settings 和网络阻断门禁隔离开发者环境；不会
因为开发 `.env` 中存在 Provider 字段就获得访问公网的权限。

## 安全规则

- `.env` 和所有非 example 环境文件必须保持 Git ignore；
- Docker 构建上下文必须排除所有 `.env.*`；
- API Key、数据库密码和完整连接秘密不得进入 Dockerfile、Compose 默认值或文档；
- API Key 不得出现在命令参数、日志、异常、测试 ID 或 snapshot；
- 示例中的本地数据库密码仅是明确的非生产占位符，使用前必须替换；
- 真实 Provider 配置必须通过当前进程或受控 Secret 注入；
- 配置错误不得触发自动 fallback、retry 或 Provider routing。

GitHub 手动 LLM Integration 使用 `llm-integration` protected environment：API Key 保存为
Environment Secret，Base URL 和默认模型保存为 Environment Variable。每个 Provider job
只接收自身配置；默认 CI、PostgreSQL Workflow、pull request 和 fork pull request 均不得
获得这些值。
