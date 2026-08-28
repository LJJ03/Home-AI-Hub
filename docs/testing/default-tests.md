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

## 环境契约门禁

Runtime Contract Tests 会验证四份受版本控制模板：

- 覆盖全部 `Settings` 和 `LLMSettings` 字段；
- 默认选择 `mock`；
- 真实 Provider 字段为空；
- local/docker/test/production 专属键不串层；
- 生产样例在数据库秘密未注入时 fail closed；
- Dockerfile 和 Compose 不包含供应商密钥；
- Git 和 Docker build context 排除真实环境文件。
