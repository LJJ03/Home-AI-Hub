# PostgreSQL Integration 测试

## 适用范围

PostgreSQL Integration 验证 PostgreSQL 17 连接、Alembic Migration、Repository CRUD 和
`/ready` 的数据库语义。它不运行真实 LLM Integration，也不改变数据库 Freeze 边界。

## 前置条件

- 可连接的 PostgreSQL 17；
- `DATABASE_URL` 使用 `postgresql+asyncpg`；
- 数据库用户能够连接 `postgres` 管理库并创建、终止连接和删除临时数据库；
- 数据库只用于测试，不得指向生产实例。

可从 `.env.test.example` 建立本地测试配置，替换其中的非生产占位密码，并通过未受版本
控制的 `.env` 或当前进程环境提供。不要提交填充后的文件。

## 运行方式

```console
cd backend
python -m pytest --run-integration
```

## GitHub Actions Workflow

`.github/workflows/postgres-integration.yml` 不是默认 CI。它只允许在 `main` 分支 push 或
通过 `workflow_dispatch` 手动触发，不响应普通或 fork pull request。Workflow 使用
Python 3.13 和 Runner 生命周期内的临时 PostgreSQL 17 service，并执行：

```console
python -m pytest --run-integration
```

Service 使用明确的 CI 测试用户名、密码和管理数据库；测试 Session 仍由既有 fixture 创建
随机隔离数据库并在结束时清理。Runner 销毁后 service 数据一并消失。它不连接开发或生产
数据库，不运行真实 LLM，不配置 Provider API Key，Provider 固定为 `mock`，也不传入
`--run-llm-integration`。

Phase 7 已取得该 Workflow 在真实 GitHub Runner 通过的证据。后续 Schema 变更仍须重新运行，
不得用历史通过结果替代当前 revision 的验证。

测试会基于配置的 PostgreSQL Server 创建名称随机且经过格式校验的独立数据库，执行全部
Alembic Migration，并在测试结束后强制清理。失败后的遗留数据库应作为异常情况人工审查，
不得通过宽泛脚本删除未知数据库。

## 隔离保证

- 默认 `python -m pytest` 不连接 PostgreSQL；
- `--run-integration` 只允许具有 `integration` marker 的测试访问数据库网络；
- 每次 Session 使用独立随机数据库；
- 不使用 `create_all()`，Schema 只通过 Alembic 建立；
- 不启用 `--run-llm-integration`；
- Redis 和真实 Provider 不参与测试。

## Phase 8 Conversation Schema 验证

Phase 8 Step 2 新增 Alembic revision `20260901_0002`，其直接父 revision 是 Phase 7
基线 `20260826_0001`。显式 PostgreSQL Integration 会先升级到该基线，再升级到唯一 head，
并验证：

- `conversations`、`conversation_turns`、`messages` 的字段与 UTC 时间类型；
- 状态、角色、正数 sequence、非负 token usage 与非空正文约束；
- Conversation 内 sequence、Turn 内角色以及幂等键唯一约束；
- `request_id` 仅用于关联，不承担幂等唯一性；
- 所有 Conversation/Turn/Message 外键采用 `ON DELETE RESTRICT`，与当前不支持 hard delete
  的领域边界一致；
- 历史 `system_info` Schema 保持可用，Alembic 最终只有一个 head。

默认 `python -m pytest` 只执行上述 Schema 和 Migration 的静态契约测试，不连接数据库；
真实约束验证仍只在显式 `--run-integration` 下运行。

## Phase 8 Conversation Repository 验证

Phase 8 Step 3 的 Repository Protocol 保持 SQLAlchemy-free；具体 Adapter 复用 Phase 3
AsyncSession 生命周期，并由 Conversation Unit of Work 独占 commit/rollback。显式
PostgreSQL Integration 还会验证：

- Conversation、Turn、Message 的 add/get/save 与 Domain Entity 返回类型；
- 归档状态保存、幂等键查询，以及重复 `request_id` 不承担幂等唯一性；
- Message sequence 顺序、游标分页和仅包含 completed Turn 的有界 Context 查询；
- Unit of Work commit、显式 rollback、未 commit 自动 rollback；
- Repository 的 flush 对其他事务不可见，证明 Repository 不会自行 commit；
- `get_for_update` 在并发事务中保持 Conversation 行锁，直到持锁事务结束。

这些测试不调用 LLM、不需要 Provider Key，也不会把 ORM Model 暴露给上层。
