# Phase 8 Conversation Domain / Chat Persistence Release Gate

## 当前结论

当前状态：**Freeze Review Completed / Final Freeze Review Pending**。

Phase 8 Implementation Step 1–7 已完成。首次 Freeze Review 已确认代码、默认测试、
PostgreSQL Integration Runner、安全门禁和冻结边界满足要求，但发现文档仍保留提交前的
Pending 状态，因此当前正在执行 docs-only cleanup。Phase 8 尚未 Freeze，`v0.8.0` 尚未
创建；Phase 7 annotated tag `v0.7.0` 保持指向 `5b411cb`，不得移动、删除或重建。

Step 7 commit `ca05ab7` 已取得真实 GitHub Runner 证据：Default Offline CI run
`33528818430` 和 PostgreSQL Integration run `33528818472` 均为 `completed / success`。
本次 cleanup 形成新 commit 后，仍须针对新的当前 revision 重新运行这两个 Workflow；
`ca05ab7` 的成功证据不会被错误复用为 cleanup commit 的证据。

Manual Real LLM workflow run `33479758528` 已 `completed / cancelled`：费用确认步骤为
`success`，DeepSeek job 为 `cancelled`，OpenAI job 为 `skipped`。没有 Waiting 或 pending
approval，deployment 未批准，Provider 未运行。Real LLM Integration：`Not Run`；
Real LLM Cost：`0`；本阶段没有配置真实 API Key。

首次 Freeze Review 证据：

| Gate | 状态 | 说明 |
|---|---|---|
| Local Python 3.13 default pytest | `Passed` | `691 passed, 9 skipped, 7 warnings` |
| Alembic revision graph | `Passed` | 唯一 head 为 `20260901_0002` |
| Local PostgreSQL Integration | `Not Run` | 本机 loopback PostgreSQL 不可用，不伪造通过 |
| `ca05ab7` Default Offline CI | `Passed` | run `33528818430`，`completed / success` |
| `ca05ab7` PostgreSQL Integration CI | `Passed` | run `33528818472`，`completed / success` |
| Manual Real LLM workflow | `Completed / Cancelled` | 未批准 deployment；DeepSeek cancelled；OpenAI skipped |
| Cleanup commit Runner evidence | `Pending` | cleanup 提交后重新运行两项 Workflow |

## 实现范围证据

| Step | 完成范围 | 当前状态 |
|---|---|---|
| 1 | Conversation、ConversationTurn、Message、状态与领域不变量 | Completed |
| 2 | SQLAlchemy ORM、`20260901_0002` Migration 与三张 Conversation 表 | Completed |
| 3 | Repository Protocol、SQLAlchemy Adapter、Mapper 与 Unit of Work | Completed |
| 4 | Command/Query/Chat Application Service 与有界 Context Builder | Completed |
| 5 | 独立 Conversation HTTP API、Schema、Dependency Wiring 与安全错误映射 | Completed |
| 6 | 默认离线、PostgreSQL Integration、API 回归、架构和秘密卫生门禁 | Completed |
| 7 | 文档、Release Evidence 与 Freeze Review 准备 | Completed |

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

首次 Freeze Review 已确认 `ca05ab7` 的实现和验证证据。本次 cleanup 会形成新的 revision，
因此只有以下项目全部由最终 Freeze Review 确认后，才能建议创建下一 annotated tag：

- [ ] Cleanup commit 后 Git working tree clean；
- [ ] Default Offline CI 在 cleanup 当前 commit 上 `Passed`；
- [ ] PostgreSQL Integration CI 在 cleanup 当前 commit 上 `Passed`；
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
- [ ] 独立最终 Freeze Review 已通过。

当前不得勾选依赖 cleanup commit 或后续 Runner 的项目，也不得提前宣布 Phase 8 Freeze。

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

- 本次 docs-only cleanup 不创建 tag；
- 不移动、删除或重建 `v0.6.0`、`v0.7.0`；
- `v0.8.0` 尚未创建；
- cleanup commit 推送并取得两个 GitHub Runner `Passed` 结果后，再执行最终 Phase 8 Freeze
  Review；
- 只有最终 Freeze Review 明确通过并取得用户单独确认后，才可以创建下一 tag；
- Phase 8 Freeze 完成前不得进入后续阶段实现。
