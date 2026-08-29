# Backend Docker 镜像说明

## 构建上下文

Docker 构建上下文是 `backend/`。该目录下的 `.dockerignore` 会在内容发送给 Docker
Daemon 前排除本地环境、测试、缓存、运行数据、日志、凭据和未来前端产物。

在项目根目录构建镜像：

```console
docker build --tag home-ai-hub-backend:local backend
```

Docker 本地运行配置应从 `.env.docker.example` 建立未受版本控制的 `.env.docker`。
不要使用宿主机本地开发模板代替，因为容器中的 PostgreSQL 主机名必须是 Compose 服务名。
基础 Compose 直接把该文件注入 Backend 和 Migration；启动时还要用 `--env-file` 让
Compose 插值读取相同配置源：

```powershell
Copy-Item .env.docker.example .env.docker
docker compose --env-file .env.docker up --build
```

不要将 Docker 模板再复制为 `.env`。真实环境文件受 Git 和 Docker build context 排除，
Compose 文件本身也不提供 API Key 或真实 Provider 默认值。

## 镜像结构

Dockerfile 使用两个 Stage：

1. `builder` 将应用及依赖构建为 Wheel；
2. `runtime` 只安装这些 Wheel、复制 Alembic Migration 资源，并以非特权 `app`
   用户运行。

Runtime Stage 使用 `--no-index` 安装，使依赖下载仅发生在 Builder Stage。最终镜像保留
Alembic，使后续 Compose Step 能够使用同一个不可变应用镜像执行一次性 Migration。

## 本地验证

以下检查不会启动 API，也不需要 Provider 凭据：

```console
docker run --rm home-ai-hub-backend:local python --version
docker run --rm --entrypoint id home-ai-hub-backend:local
```

预期结果是 Python 3.13.15 和非 root 运行身份。

启动 API 时必须注入现有应用和 LLM 配置。离线运行应使用 `LLM_PROVIDER=mock`。
不得通过 Dockerfile 的 `ARG` 或 `ENV` 传入秘密，也不得提交包含真实值的环境文件。

## Healthcheck

镜像 healthcheck 使用 Python 标准库请求 `APP_PORT`（默认 `8000`）上的 `/health`。
镜像不为此安装 `curl`，也不改变已经冻结的 `/ready` 数据库语义。

## Compose 服务拓扑

基础本地拓扑包含四个职责独立的服务：

1. `postgres` 使用 PostgreSQL 17、持久化 named volume 和 `pg_isready` healthcheck；
2. `redis` 使用独立 named volume 和 `redis-cli ping`，仅作为未来能力的运行时预留；
3. `migration` 与 Backend 使用同一镜像，在 PostgreSQL healthy 后一次性执行
   `python -m alembic upgrade head`；
4. `backend` 仅在 PostgreSQL healthy 且 Migration 成功后启动，不在自身启动命令中运行
   Migration 或测试。

Migration 独立可以让 schema 失败阻断应用启动，并避免多副本并发迁移。Redis 不属于
Backend 的依赖，也不进入 `/ready`。容器 healthcheck 使用 `/health` 检查进程存活；
`/ready` 保持冻结的 PostgreSQL readiness 语义，且不远程探测 LLM。

默认配置为 `LLM_PROVIDER=mock`，因此本地 Compose 不需要 API Key，也不会进行真实 LLM
调用。选择真实 Provider 必须由操作者在受控运行环境显式注入完整配置，并保留 fail-fast。

## Compose 文件分层

- `docker-compose.yml`：本地基础拓扑，包含 PostgreSQL、Redis、Migration 和 Backend；
- `docker-compose.dev.yml`：可选开发增强，目前只提高日志级别；
- `docker-compose.test.yml`：只启动隔离的 PostgreSQL 17 测试服务，默认映射宿主机
  `5433` 并使用临时数据目录；
- `docker-compose.production.example.yml`：外部镜像与数据库注入契约样例。

开发增强暂不启用 bind mount 或 reload。当前机器无法进行 Docker 动态验证，在此之前
覆盖已构建 wheel 可能造成宿主机与镜像代码不一致。需要叠加开发配置时使用：

```powershell
docker compose --env-file .env.docker -f docker-compose.yml -f docker-compose.dev.yml up --build
```

生产 Compose 只是部署契约说明，不是可直接上线的配置或秘密管理方案。它要求平台显式
提供不可变镜像引用和数据库连接，不含 build、bind mount、reload 或 API Key。真实生产
凭据必须由 Secret Manager 或部署平台注入。

## 验证状态

默认 pytest 使用 YAML 静态解析验证服务、依赖顺序、healthcheck、Migration、配置接线及
敏感信息边界，不依赖 Docker daemon。本机未安装 Docker、Podman、nerdctl 或 buildah，
因此 `docker compose config`、镜像构建、服务启动和端点 Smoke Test 尚未执行；这不会被
描述为动态验证通过。

完整配置矩阵见[环境变量分层与安全边界](environment.md)。
正式发布还必须按 [Phase 7 Release Gate](release-gate.md) 分别记录 image build/run、
Compose config/up、Migration 和 `/health`、`/ready`、`/version` 动态结果。当前这些项目
均为 `Not Run`，不能由静态 Compose 契约替代。
