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
job 注入一套 Provider 配置；缺失配置在 pytest 前 fail closed。没有明确的真实调用授权、
成本确认和完整 Provider 配置时，不得批准 protected-environment deployment。

## 当前运行状态

- GitHub account Billing Lock 已解除；
- Default Offline CI 已在真实 GitHub Runner 上通过；
- PostgreSQL Integration CI 已在真实 GitHub Runner 上通过；
- Manual LLM Workflow 在未确认费用时按预期 fail closed；
- 确认费用后，DeepSeek job 在 `llm-integration` protected environment 进入
  `Waiting for review`，验证人工审批路径后已取消；OpenAI job 为 `Skipped`；
- deployment 未获批准，真实 DeepSeek/OpenAI Integration 为 `Not Run`，费用为 `0`；
- 只有在未来取得明确真实调用授权、成本确认并配置目标
  Provider 后，才可以批准 deployment。

Phase 7 的 Default Offline CI 与 PostgreSQL Integration CI 证据关联 commit `5b411cb`；
Manual LLM 审批路径证据关联 commit `2fe129e`。后续 Release Gate 记录仍应保存对应 run
URL、触发方式和时间，并保持日志无秘密、Prompt 或模型正文。Phase 7 Release Gate 当前
状态为 `Passed / Freeze`，annotated tag `v0.7.0` 已发布且不得移动或重建。Phase 8 Step 7
commit `ca05ab7` 的 Default Offline CI run `33528818430` 与 PostgreSQL Integration run
`33528818472` 均已 `completed / success`。首次 Phase 8 Freeze Review 已完成；docs-only
cleanup 形成新 revision 后，必须再次取得这两个 Workflow 的 Runner `Passed` 证据，才能
执行最终 Phase 8 Freeze Review。`v0.8.0` 尚未创建。

完整发布判定见 [Phase 7 Release Gate](release-gate.md)。
