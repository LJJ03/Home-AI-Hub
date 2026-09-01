# Phase 8 Conversation Domain / Chat Persistence Release Gate

## 当前结论

当前状态：**Freeze Review Pending**。

Phase 8 Implementation Step 1–6 已完成，Step 7 只负责文档、Release Evidence 与 Freeze
Preparation。Phase 8 尚未 Freeze，当前不得创建新 tag；Phase 7 annotated tag `v0.7.0`
保持指向 `5b411cb`，不得移动、删除或重建。

Step 6 commit `ac11520` 已取得 Default Offline CI 与 PostgreSQL Integration CI 的真实
GitHub Runner `Passed` 证据。Step 7 文档提交后必须针对新的当前 commit 重新运行这两个
Workflow；历史 revision 的成功不能替代 Freeze Review 所需的当前 revision 证据。

Manual Real LLM Integration：`Not Run`。Real LLM Cost：`0`。没有批准 deployment，没有
运行 DeepSeek/OpenAI Provider，也没有为本阶段配置真实 API Key。

当前 Step 7 工作树证据：

| Gate | 状态 | 说明 |
|---|---|---|
| Local Python 3.13 default pytest | `Passed` | `691 passed, 9 skipped, 7 warnings` |
| Alembic revision graph | `Passed` | 唯一 head 为 `20260901_0002` |
| Local PostgreSQL Integration | `Not Run` | 本机 loopback PostgreSQL 不可用，不伪造通过 |
| Step 7 current-commit Default Offline CI | `Pending` | 文档尚未提交，提交后重跑 |
| Step 7 current-commit PostgreSQL Integration CI | `Pending` | 文档尚未提交，提交后重跑 |

## 实现范围证据

| Step | 完成范围 | 当前状态 |
|---|---|---|
| 1 | Conversation、ConversationTurn、Message、状态与领域不变量 | Completed |
| 2 | SQLAlchemy ORM、`20260901_0002` Migration 与三张 Conversation 表 | Completed |
| 3 | Repository Protocol、SQLAlchemy Adapter、Mapper 与 Unit of Work | Completed |
| 4 | Command/Query/Chat Application Service 与有界 Context Builder | Completed |
| 5 | 独立 Conversation HTTP API、Schema、Dependency Wiring 与安全错误映射 | Completed |
| 6 | 默认离线、PostgreSQL Integration、API 回归、架构和秘密卫生门禁 | Completed |
| 7 | 文档、Release Evidence 与 Freeze Review 准备 | In Progress until committed and rerun |

## 公共边界确认

- 既有 `POST /api/v1/chat/completions` 继续保持无状态，JSON/SSE 契约未改变；
- `ChatRequest` 不接受 `conversation_id`，无状态 Chat 不读取或写入 Conversation 数据；
- Conversation API 位于独立 `/api/v1/conversations` 边界，只提供已文档化的六个 endpoint；
- Conversation 持久化只支持非流式最终 Assistant Message，不保存 SSE chunk；
- Application Service 只通过稳定 LLMService 边界生成，不调用具体 Provider；
- Domain/Application/Repository Protocol 不反向依赖 FastAPI、SQLAlchemy Adapter 或 Provider；
- `/health`、`/ready`、`/version` 语义不变，`/ready` 不执行远程 LLM 探活；
- Phase 3–7 的 Persistence、Provider、Chat、Runtime、Docker 与 CI Freeze 边界保持不变。

## 明确未实现范围

Phase 8 没有实现持久化 SSE、User、Auth、JWT、RAG、Embeddings、向量数据库、Agent、Tool
Calling、Function Calling、MCP、Home Assistant、WebSocket、前端、多模态、Redis 业务逻辑、
自动 retry、Provider fallback 或 Provider routing。

## Freeze Review Checklist

只有以下项目全部由 Freeze Review 确认后，才能建议创建下一 annotated tag：

- [ ] Git working tree clean；
- [ ] Default Offline CI 在 Step 7 当前 commit 上 `Passed`；
- [ ] PostgreSQL Integration CI 在 Step 7 当前 commit 上 `Passed`；
- [ ] 本地 Python 3.13 默认 `python -m pytest` `Passed`；
- [ ] Alembic 唯一 head 为 `20260901_0002`；
- [ ] Phase 3–7 冻结边界未被破坏；
- [ ] 既有无状态 Chat API 契约未改变；
- [ ] 独立 Conversation API 契约已完整记录；
- [ ] Real LLM Integration 保持 `Not Run`；
- [ ] Real LLM Cost 为 `0`；
- [ ] Git 历史和版本化文件不包含真实 API Key 或其他秘密；
- [ ] Dockerfile、Compose topology 与 GitHub workflow 没有非预期变化；
- [ ] 没有等待审批或已获批准的 Manual LLM workflow deployment；
- [ ] Phase 8 Implementation Step 1–7 范围完整且无越界功能；
- [ ] 独立 Freeze Review 已通过。

当前不得勾选依赖 Step 7 commit 或后续 Runner 的项目，也不得提前宣布 Phase 8 Freeze。

## 验证入口

默认离线测试：

```console
cd backend
python -m pytest
```

PostgreSQL Integration：

```console
cd backend
python -m pytest --run-integration
```

本机 PostgreSQL 不可用时必须记录为 `Not Run`。提交后通过 GitHub Runner 取得当前 commit
证据，不得伪造或复用旧 revision 的结果。真实 LLM Integration 不属于本 Step 的执行范围。

## Tag 与后续步骤

- 本 Step 不创建 tag；
- 不移动、删除或重建 `v0.6.0`、`v0.7.0`；
- Step 7 提交并取得两个 GitHub Runner `Passed` 结果后，才能单独执行 Phase 8 Freeze Review；
- 只有 Freeze Review 明确通过后，才可以建议下一 tag 的命令；
- Freeze Review 前不得进入后续阶段实现。
