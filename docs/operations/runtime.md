# Backend Runtime 运维说明

## 适用范围

Backend Runtime 负责打包已经冻结的 Phase 3-6 应用，不改变 Persistence、LLM
Provider、Chat API 或 Migration 公共契约。运行时固定为 Python 3.13.15，并通过现有
入口 `python -m app` 启动。

## 进程模型

- 容器运行单个 Uvicorn 应用进程；
- 启动命令使用 Docker exec-form，确保终止信号能够直接传递给 Python；
- FastAPI Lifespan 继续负责应用持有的数据库和 LLM 资源；
- 应用配置只在运行时注入，环境文件和凭据不会复制进镜像。

## 容器用户

Runtime Stage 创建非特权用户 `app`，默认 UID 和 GID 均为 `10001`。部署平台需要其他
非 root 身份时，可在镜像构建阶段覆盖这两个 ID。最终应用进程不会切换回 root。

## 健康检查语义

镜像 healthcheck 调用进程存活端点 `/health`，有意不调用 `/ready`：

- `/health` 只确认 API 进程能够响应；
- `/ready` 保持已经冻结的 PostgreSQL readiness 语义；
- LLM Provider 和 Redis 不加入镜像 liveness，也不进行 LLM 远程探活。

部署和发布 Smoke Test 必须在数据库迁移完成后单独检查 `/ready`。

## 安全边界

Runtime 镜像不得包含本地虚拟环境、测试缓存、日志、数据库数据、私钥、API Key、
Authorization Header 或 Provider 凭据。Provider 配置只能在容器启动时注入。

镜像通过项目现有依赖安装 HTTP Adapter，不安装 OpenAI、DeepSeek 或其他供应商 SDK。
