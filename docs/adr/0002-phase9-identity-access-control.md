# Phase 9 Identity and Access Control Baseline

- ADR：0002
- 状态：Accepted
- 日期：2026-09-02
- 决策范围：Phase 9 Identity、Access Control、Conversation Ownership 与 Trusted Deployment
- 关联设计：[Phase 9 Identity / Access Control / Trusted Deployment Architecture Design](../architecture/phase9-identity-access-control.md)

## 背景

Phase 8 已实现 Conversation、ConversationTurn 和 Message 的持久化，并通过独立
Conversation API 提供资源访问。Conversation 已经是长期存在的资源，其历史消息、模型
调用和状态不能继续依赖“知道 UUID 即可访问”的隐含规则。UUID 是资源标识符，不是访问
控制机制。

后续 Home Assistant、Agent、Tool Calling 和 RAG 都需要可信 ActorContext。它们可能读取
私有历史、产生供应商费用，或者对家庭设备和外部系统造成真实影响。长期保持无 Auth 会
扩大以下风险：

- 历史 Conversation 被未授权读取或修改；
- API 暴露到局域网或公网后被任意调用；
- 模型调用产生不可归属的费用；
- 未来设备控制和工具执行缺少主体、授权与审计；
- 日志或泄漏的 UUID 被误当作访问凭据。

因此，Phase 9 必须先建立身份、访问控制、Conversation ownership 和可信部署基线，再考虑
更高权限能力。

## 决策

### 决策一：最小 User 与不透明 API Token — Accepted

第一阶段正式接受以下方案：

1. 建立最小 User，作为 Conversation owner 和已认证人类主体；
2. 使用数据库管理的高熵、不透明 API Token；
3. 每个 User 可以拥有多个独立、可过期、可撤销的 Token；
4. Token 只保存不可逆 hash，不保存明文；
5. 原始 Token 只允许在创建时显示一次；
6. 不采用 JWT；
7. 不采用 OAuth/OIDC；
8. 不采用 Session Cookie；
9. 不实现完整 RBAC，只使用最小、固定的 scopes/capabilities 与 ownership policy。

API Token 使用 Bearer credential 传输，但不具备 JWT 的自包含声明。Token record 通过公开
identifier 定位，秘密部分使用带服务器端 pepper 的 keyed hash 和 constant-time comparison
验证。Authorization Header、Token 明文和 Token hash 均不得进入日志、异常或审计正文。

### 决策二：Trusted Local Mode 仅作受约束过渡 — Accepted

Trusted Local Mode 只允许作为本地开发或明确受信本地部署的过渡模式：

1. 必须由显式配置启用；
2. 优先只允许 loopback 或受控本地入口；
3. 必须明确记录它不提供调用者凭据隔离；
4. 不得用硬编码或虚假 User ID 冒充多用户；
5. ownership 启用后，必须绑定安装者显式创建的真实 installation-owner User；
6. 生产环境不得默认启用或静默回退到 Trusted Local Mode；
7. 生产环境认证模式、Token pepper 或必要安全配置缺失时必须 fail fast。

该模式不是公网部署方案，也不能作为未来 Home Assistant、Agent 或 Tool Calling 绕过认证的
入口。

### 决策三：Conversation 单一所有权 — Accepted

Conversation 第一版正式采用单一 `owner_user_id`：

1. 一个 Conversation 只有一个真实 User owner；
2. create、list、get、messages、create turn 和 archive 都必须执行 ownership policy；
3. list 和读取查询必须在持久化查询层按 owner scope，不能只依赖 Router 检查；
4. 第一版不实现共享、多 owner、组织、租户或复杂 RBAC；
5. 遗留 Conversation 不得静默分配给虚假、硬编码或隐式默认用户；
6. 遗留数据只能回填到安装者显式创建并选择的真实 User；
7. 无法确认 owner 的历史数据必须 fail closed，保持不可访问或阻止完成迁移。

未来需要资源共享时，应通过新的独立决策和 additive Migration 引入 membership/ownership
关系，不提前改变本决策。

## 应用与 API 边界

- Router 只负责提取凭据、调用认证入口并注入不可变 ActorContext；
- Authorization 集中在 Application Layer，不散落在 Router；
- Conversation Service 不解析 Token；
- Application Layer 不依赖 FastAPI、SQLAlchemy，也不读取环境变量；
- `/api/v1/chat/completions` 的请求、JSON/SSE DTO 和 Provider 边界保持不变，认证作为外层
  访问策略；
- Conversation API 保持独立，通过 ActorContext、capability 和 ownership 控制访问；
- `/health`、`/ready` 和 `/version` 保持既有最小匿名系统端点语义；
- `/ready` 不执行外部认证服务或 LLM 远程探活。

## 安全与审计边界

不得记录或持久化：

- Authorization Header；
- Token 明文或 Token hash；
- Cookie；
- Message content；
- Prompt；
- 完整 Response；
- SSE Chunk；
- Provider 原始响应或错误体；
- 数据库连接密码；
- 内部堆栈。

Audit 只允许记录经过 allowlist 的 Actor 类型、User ID、action、outcome、resource ID、
request ID、安全错误码和时间等元数据。

## 数据迁移约束

- 不修改 `20260901_0002` 或其他历史 Migration；
- 未来 Migration 必须从当前 Alembic head 继续；
- 不使用 `create_all()`；
- owner 字段先以可迁移方式加入，再通过受控流程创建真实 User 并回填；
- 回填完成且验证无 owner 行为零后，才允许增加非空约束；
- PostgreSQL Integration 必须验证 Migration、外键、唯一约束、回填和 fail-closed 行为。

## 结果

该决策为 Conversation 历史、模型费用和未来设备操作建立统一主体边界，并为 Home
Assistant、Agent、Tool Calling 和 RAG 提供可复用的 ActorContext、Authorization 和 Audit
基础。

代价包括：

- 部署需要显式创建真实 installation owner 和 API Token；
- 遗留 Conversation 需要受控回填；
- 生产启动配置更严格；
- 现有 Chat 和 Conversation API 在安全模式下会新增 401、403 或安全 404 行为；
- Migration、Repository、Application 和 API 需要新增跨层安全测试。

这些代价是持久化数据和未来高权限功能所要求的安全成本，不能通过静默 fallback 规避。

## 被拒绝或推迟的替代方案

- 长期保持无 Auth：拒绝，因为 UUID 无法提供身份、授权或审计；
- 单一共享环境变量 Token：拒绝，因为无法按 User 撤销、轮换和归属；
- JWT：第一版拒绝，因为声明、签名、撤销和生命周期复杂度超过当前需求；
- OAuth/OIDC：推迟，待外部身份和多用户需求明确后再设计；
- Session Cookie：推迟，当前没有前端登录和浏览器会话需求；
- 完整 RBAC：推迟，第一版使用固定 capability 加 ownership；
- Conversation ownership table：推迟，单 owner 使用 `owner_user_id` 更小且清晰；
- 虚假默认用户或静默 owner 回填：拒绝，因为会伪造所有权事实；
- Router 内分散授权：拒绝，因为难以复用、审计和测试；
- 在 Home Assistant、Agent 或 Tool Calling 中建立认证旁路：拒绝。

## 实施前置条件

本 ADR 的 Accepted 状态只表示架构决策已接受，不表示 Phase 9 implementation 已开始。
开始 Step 1 前仍必须满足主架构文档中的 Entry Criteria，并取得用户单独授权。当前不得
创建 `v0.9.0`，不得运行真实 LLM，也不得修改 Phase 3–8 冻结公共边界。
