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
当前 Compose 尚未直接读取 `.env.docker`；Step 4 接线完成前仍需按环境分层文档提供兼容
的 `.env`，不得据此提前声明 Compose 分层完成。

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

## Compose 边界

Phase 7 Step 2 不修改 `docker-compose.yml` 或其启动链。PostgreSQL 健康顺序、一次性
Migration 服务和 Compose Runtime 验证仍属于后续经确认的 Phase 7 Step。

完整配置矩阵见[环境变量分层与安全边界](environment.md)。
