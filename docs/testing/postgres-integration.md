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
