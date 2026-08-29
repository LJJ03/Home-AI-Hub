# CI 与 Integration Workflows

## Workflow 矩阵

| Workflow | 触发 | 命令 | 外部资源 | Secrets |
|---|---|---|---|---|
| Default Offline CI | push、pull request | `python -m pytest` | 测试阶段无公网；无 Docker | 无 |
| PostgreSQL Integration | main push、workflow_dispatch | `python -m pytest --run-integration` | 临时 PostgreSQL 17 | 无 LLM secrets |
| Manual Real LLM Integration | workflow_dispatch | `python -m pytest --run-llm-integration` | 被选真实 Provider | protected environment 中被选 Provider 的 Secret |

三个 Workflow 均使用 Python 3.13、`contents: read` 和不持久化的 Checkout 凭据。默认 CI
不继承 Integration 服务、开关、成本确认或 secrets。依赖安装阶段可能访问包仓库；默认
测试执行阶段由项目 Network Gate 阻断公网 DNS/Socket 并允许 loopback。

## PostgreSQL Integration

PostgreSQL Workflow 不响应 pull request，使用 Runner 生命周期内的 PostgreSQL 17 service
和 CI 专属凭据。既有 fixture 创建随机隔离数据库，执行 Alembic、Repository 和 readiness
验证并清理。它固定 Mock Provider，不运行真实 LLM。

## Manual LLM Integration

真实 LLM Workflow 只能手动触发。`acknowledge_cost` 必须为 true，且 DeepSeek/OpenAI
专属 job 都绑定 `llm-integration` protected environment。仓库管理员必须配置 required
reviewers、对应 API Key Secret、Base URL Variable 和默认模型 Variable。每次运行只向被选
job 注入一套 Provider 配置；缺失配置在 pytest 前 fail closed。

## 当前运行状态

> GitHub Actions runtime execution: Not Run — workflows created but not triggered on GitHub Runner.

因此不能声称默认 CI、PostgreSQL Integration 或 Manual LLM Integration 已在 GitHub 上
通过。运行证据必须关联 commit SHA 和 run URL，并保持日志无秘密、Prompt 或模型正文。

完整发布判定见 [Phase 7 Release Gate](release-gate.md)。
