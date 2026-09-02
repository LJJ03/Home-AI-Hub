# Phase 9 — Identity / Access Control / Trusted Deployment Architecture Design

状态：**Architecture Decision Accepted / Implementation Not Started**。

Phase 1–8 已冻结。Phase 8 annotated tag `v0.8.0` 已存在，且不得移动、删除或重建。
本文只固化 Phase 9 架构决策，不代表任何 User、Auth、API、ORM 或 Migration 已实现，也不
授权进入 Phase 9 implementation。

正式决策记录见 [ADR 0002: Phase 9 Identity and Access Control Baseline](../adr/0002-phase9-identity-access-control.md)。

## 架构决策摘要

Phase 9 推荐采用以下方案：

1. 显式区分 Actor、Principal、User、Identity 与资源所有权；
2. 第一阶段实现最小 User 和数据库管理的不透明 API Token；
3. 不采用 JWT，不采用 OAuth/OIDC；
4. Trusted Local Mode 只作为受约束的本地过渡模式；
5. 生产环境必须显式启用安全认证并 fail fast，不得回退到 Trusted Local Mode；
6. Conversation 初期采用单一 `owner_user_id`；
7. 遗留 Conversation 只能回填到安装者显式创建的真实 User；
8. Router 只提取凭据并注入 ActorContext，Authorization 集中在 Application Layer；
9. Token 只保存不可逆 hash，不保存明文；
10. Authorization Header、Token、Message、Prompt、Response 和 Chunk 不得进入日志；
11. Home Assistant、Agent、Tool Calling、RAG、前端和 WebSocket 不属于 Phase 9 第一版。

## 1. 阶段定位

Phase 8 已经让 Conversation、ConversationTurn 和 Message 成为持久化资源。持久化以后，
系统必须回答谁创建和拥有 Conversation、谁能读取历史、谁能追加 Turn、谁能归档资源，
以及谁能触发可能产生费用或现实影响的操作。

UUID 只能降低资源标识符被枚举的概率，不能充当访问控制。UUID 一旦通过日志、浏览器
历史、截图或错误报告泄漏，没有所有权检查的接口仍可能被越权访问。

Home Assistant、Agent 和 Tool Calling 会把风险从文本处理扩大到真实设备和外部系统操作；
RAG 会引入私有文档和知识权限；前端和移动端会扩大 API 暴露面。因此必须先设计身份、
所有权、授权和审计边界，再引入这些能力。

当前单用户可信部署假设可以作为受约束的迁移起点，但不能无限延伸到局域网、公网或
多用户场景。

## 2. Phase 9 目标

Phase 9 的目标是：

- 定义 Actor、Principal、Identity、User 和未来 Service Principal 的边界；
- 为 Conversation 建立明确的单一所有权；
- 为 Chat 和 Conversation API 建立认证与授权入口；
- 支持安全的单用户家庭部署，并保留未来多用户迁移路径；
- 选择第一阶段认证方式；
- 集中定义授权策略，避免规则散落在 Router；
- 建立安全、稳定的认证和授权错误映射；
- 建立不含敏感正文的审计边界；
- 明确用户 Token、Provider API Key 和部署 Secret 的不同职责；
- 建立默认离线、PostgreSQL Integration 和安全测试策略；
- 为未来 Home Assistant、Agent 和 Tool Calling 提供可信 ActorContext。

## 3. Phase 9 非目标

当前 Architecture Design 阶段不实施任何功能，尤其不：

- 实现 Auth；
- 创建 User 表或其他 ORM Model；
- 实现 JWT；
- 接入 OAuth/OIDC；
- 实现 Session Cookie；
- 实现前端登录；
- 实现多租户；
- 实现完整 RBAC；
- 新增 API endpoint；
- 修改 Conversation API 或 `/api/v1/chat/completions`；
- 接入 Home Assistant；
- 实现 Agent、Tool Calling、RAG、前端或 WebSocket；
- 运行真实 LLM；
- 创建或修改 Alembic Migration；
- 创建任何 tag。

未来 Phase 9 第一版 implementation 建议实现最小 User、API Token、ActorContext 和
Conversation Ownership。JWT、OAuth/OIDC、Session、复杂 RBAC 和多租户继续推迟。

## 4. 为什么不能长期保持无 Auth

长期无认证会产生以下风险：

- 任意调用者都能读取 Conversation history；
- Conversation ID 被猜中或泄漏后，资源可能被直接访问；
- 局域网内受感染设备可能调用 Chat 或 Conversation API；
- API 暴露到公网后，扫描器可以直接发起请求；
- Chat Completion 会产生模型调用和费用；
- Home Assistant 接入会产生灯光、门锁、空调等真实世界影响；
- Agent 和 Tool Calling 会扩大可执行操作范围；
- 日志、错误和调试接口可能扩大信息泄漏面；
- 无 ActorContext 时无法可靠审计谁执行了什么；
- 后补权限时，缺乏迁移策略会留下无法安全判定 owner 的历史数据。

因此，无 Auth 只能是显式、受约束的本地过渡模式，不能成为隐含的生产安全假设。

## 5. 推荐身份模型

### Actor

Actor 表示一次应用操作的实际发起者，是 Application Layer 使用的安全主体。ActorContext
不得包含原始 Token、Authorization Header、Cookie 或 Provider Key。

### Principal

Principal 表示认证结果，而不是数据库 User 本身。推荐概念包括：

- `AuthenticatedPrincipal`；
- `AnonymousPrincipal`；
- `TrustedLocalPrincipal`；
- `SystemPrincipal`；
- 未来的 `ServicePrincipal`。

### AuthenticatedPrincipal

由有效 API Token 认证后产生，至少携带：

- 稳定的 User ID；
- Principal 类型；
- authentication method；
- 固定、受控的 scopes 或 capabilities；
- Token record ID，而不是 Token 明文；
- request correlation ID。

### AnonymousPrincipal

允许存在，但只能访问明确匿名开放的系统端点：

- `/health`；
- `/ready`；
- `/version`。

AnonymousPrincipal 不得访问 Chat 或 Conversation 资源。

### TrustedLocalActor

Trusted Local Mode 是单用户本地部署的过渡机制，必须满足：

- 由显式配置启用；
- 默认只允许 loopback 或受控本地入口；
- 文档明确说明它不提供凭据隔离；
- 不得用硬编码或虚假的 User ID 冒充多用户；
- Conversation ownership 启用后，必须绑定安装者显式创建的真实 installation-owner User；
- 生产环境不得静默启用或回退到该模式。

### SystemPrincipal

SystemPrincipal 只用于受控的内部迁移、维护或后台任务：

- 不能由外部 HTTP Header 构造；
- 不能自动拥有所有用户资源；
- 必须具备明确的内部 capability；
- 高风险操作必须进入安全审计边界。

### ServicePrincipal

为未来 Home Assistant 或其他服务集成预留，但 Phase 9 第一版不实现。未来服务身份必须
拥有独立凭据和 scopes，不能复用人类用户 Token。

### 所有权

第一版采用单一所有权：

- 一个 Conversation 只有一个 owner；
- owner 必须是真实 User；
- Conversation 列表、详情、消息、追加 Turn 和归档均受 owner 限制；
- UUID 不能绕过所有权；
- 暂不支持资源共享、组织或租户。

## 6. 数据模型草案

本节只描述未来模型，不创建 ORM 或 Migration。

| 模型 | Phase 9 第一版建议 | 说明 |
| --- | --- | --- |
| `users` | 实现 | 最小本地用户身份，不包含密码登录 |
| `identities` | 暂缓 | OAuth/OIDC 引入后再表示外部身份 |
| `sessions` | 暂缓 | 当前不采用 Cookie Session |
| `api_tokens` | 实现 | 每个 User 可以拥有多个可撤销 Token |
| `actor_audit_events` | 实现最小版本 | 保存安全元数据，不保存敏感正文 |
| `conversation_ownerships` | 暂缓 | 初期单 owner 直接使用 `owner_user_id` |

### users

建议字段包括随机 UUID 主键、display name、active/disabled 状态、created_at、updated_at 和
disabled_at。第一版不需要 email、password hash、OAuth provider 或 tenant 字段。

### api_tokens

建议字段包括：

- 随机 Token record UUID；
- User ID；
- 不敏感的 public token identifier；
- token hash；
- hash algorithm/version；
- label；
- scopes；
- expires_at；
- revoked_at；
- last_used_at；
- created_at。

Token 明文只在创建时显示一次，不得落库或进入日志。

### conversations.owner_user_id

第一版推荐直接为 conversations 增加 owner 外键，因为当前只支持一个 owner。未来需要
共享时再新增 membership/ownership table，不提前引入多对多复杂度。该字段属于未来新增
Migration，不修改 Phase 8 历史 Migration。

### actor_audit_events

建议保存：

- event ID；
- occurred_at；
- actor type；
- User ID，可为空；
- authentication method；
- action；
- outcome；
- resource type；
- resource ID；
- request ID；
- 安全错误码；
- 经过 allowlist 限制的 metadata。

Audit Event 不得保存 Token、Authorization Header、Message、Prompt、Response 或 Chunk。

## 7. API 认证方案比较

| 方案 | 实现复杂度 | 安全性 | 本地家庭部署 | 前端/移动端 | Home Assistant | 多用户扩展 | 测试复杂度 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Local-only trusted mode | 低 | 低 | 高 | 低 | 中 | 低 | 低 |
| 静态共享 Token | 低 | 中低 | 高 | 中 | 高 | 低 | 低 |
| 数据库管理的不透明 API Token | 中 | 高 | 高 | 中高 | 高 | 中高 | 中 |
| Session Cookie | 中高 | 高 | 中 | 高 | 低 | 高 | 高 |
| JWT | 高 | 中高 | 中 | 高 | 高 | 高 | 高 |
| OAuth/OIDC | 很高 | 高 | 中 | 高 | 高 | 很高 | 很高 |
| Reverse Proxy Auth | 中 | 取决于代理配置 | 高 | 中 | 中 | 中 | 中高 |

### 推荐方案

Phase 9 推荐：

- 开发环境使用显式 Trusted Local Mode；
- 生产和受信局域网部署使用数据库管理的不透明 API Token；
- HTTP 使用标准 Bearer credential 传递不透明 Token；
- 不使用自包含 JWT；
- 不使用单一共享环境变量 Token；
- 不实现 Session 或 OAuth/OIDC；
- Reverse Proxy Auth 只作为未来部署选项。

API Token 应使用至少 256 位随机秘密。数据库通过 public identifier 定位 Token record，再
使用带服务器端 pepper 的 keyed hash 和 constant-time comparison 验证秘密。

## 8. 推荐 Phase 9 架构方案

### Phase 9A：Trusted Local Mode 明确化

职责：

- 把当前隐含单用户假设变成显式运行模式；
- 限制绑定地址和部署环境；
- 为本地开发创建明确的 TrustedLocal ActorContext。

不负责多用户隔离、公网安全或 Token 管理。生产环境若未选择安全认证模式必须 fail fast，
不得回退到 Trusted Local Mode。

### Phase 9B：Opaque API Token Auth

职责：

- 高熵 Token 创建、验证、过期和撤销；
- Token hash 持久化；
- 创建 AuthenticatedPrincipal。

不负责 JWT、Cookie Session、OAuth 或密码登录。Token 管理第一版建议使用受控管理命令或
部署初始化流程，不新增公共 Token 管理 API。

### Phase 9C：ActorContext 注入

API Adapter 负责提取凭据并调用 Authentication Service，随后把不可变 ActorContext 传入
Application Service。Router 不解析授权策略，Conversation Service 不解析 Token。

### Phase 9D：Conversation Ownership

职责：

- 创建 Conversation 时原子写入 owner；
- 所有查询按 owner scope；
- 读取、追加 Turn、归档前执行所有权策略；
- 对遗留无 owner 数据 fail closed。

不负责 Conversation 分享、多 owner、组织或租户。

### Phase 9E：Audit Boundary

负责记录认证、拒绝、Token 生命周期和资源变更事件，并通过 request ID 关联。审计事件只
包含 allowlist 元数据，不保存敏感正文。

未来 Home Assistant 和 Agent 必须复用同一 ActorContext、授权和审计边界，不得建立旁路。

## 9. 对现有 API 的影响

### `/api/v1/chat/completions`

该端点应受认证保护，因为它能够产生模型调用和费用：

- API Token Mode 要求有效 ActorContext 和 `chat:complete` capability；
- Trusted Local Mode 注入显式 TrustedLocal ActorContext；
- 不修改现有 ChatRequest、ChatResponse 或 SSE DTO；
- 不让 Chat API 感知具体 Provider；
- 认证是外层访问策略，不改变 Phase 5/6 Provider 公共边界。

### Conversation API

六个 Conversation endpoint 都应要求 ActorContext：

- create：owner 为当前 Actor 对应的真实 User；
- list：只列出 owner 资源；
- get/messages：只读取 owner 资源；
- create turn/archive：同时要求 ownership 和相应 capability。

### 系统端点

建议继续保持：

- `/health` 匿名并只返回最小 liveness 信息；
- `/ready` 匿名并保持既有 readiness 语义；
- `/version` 匿名并保持既有契约。

部署方可以在 Reverse Proxy 层进一步限制这些端点，但应用不得破坏已冻结的响应契约。

### 配置模式

未来建议设计显式 `AUTH_MODE`，只允许 `trusted_local` 或 `api_token`。开发环境可以显式使用
Trusted Local Mode；生产环境必须显式选择 API Token Mode。缺少 Token pepper、数据库或
必要安全参数时必须在启动组合阶段 fail fast，不得 fallback。

## 10. Application Layer 设计

### ActorContext

ActorContext 是不可变、请求级 Application DTO，包含 Principal kind、User ID、认证方式、
scopes/capabilities、Trusted Local 标记和 request ID。它不得包含原始 Token 或 Header。

### AuthenticationService

协调 Token Validation Port 并创建 Principal。它不依赖 FastAPI、SQLAlchemy，也不读取环境
变量。

### AuthorizationService

负责 capability 判定和统一授权结果，不负责凭据提取或 Token hash 验证。

### OwnershipPolicy

纯规则对象，判断 Actor 是否拥有指定资源，不执行 SQL。

### ConversationAccessPolicy

组合 capability 与 ownership，集中决定是否可以创建、读取、追加 Turn 或归档 Conversation。

### API Token Validation Port

定义 Token 验证边界，由基础设施 Adapter 实现：查找 Token record、验证 hash、检查过期与
撤销、检查 User 状态，并返回安全认证结果。

### Password Hashing Port

Phase 9 第一版不需要。只有未来加入密码登录时才引入，避免为未实现能力提前抽象。

### Audit Port

建议引入。Application Service 只发送结构化安全事件，不知道数据库表、日志框架或外部
审计实现。

### 依赖规则

- Application Layer 不依赖 FastAPI；
- Application Layer 不依赖 SQLAlchemy；
- Application Layer 不读取环境变量；
- Authorization 不散落在 Router；
- Conversation Service 不解析 Token；
- API Adapter 只负责凭据提取、ActorContext 注入和安全错误映射；
- Persistence 不依赖 API、ChatService 或 LLM Provider。

## 11. Persistence 设计

未来第一版推荐新增 UserModel、ApiTokenModel、AuditEventModel 和
ConversationModel.owner_user_id，暂不新增 IdentityModel、SessionModel、RoleModel、
TenantModel 或 ConversationOwnershipModel。

### Migration 顺序

1. 从 `20260901_0002` 创建新的独立 Alembic revision；
2. 创建 users、api_tokens 和 actor_audit_events；
3. 为 conversations 增加暂时 nullable 的 owner_user_id；
4. 通过受控初始化流程创建实际 installation owner；
5. 由安装者显式选择该真实 User，对遗留 Conversation 做可审计回填；
6. 校验没有未归属行；
7. 后续 revision 将 owner_user_id 改为非空并建立索引和外键；
8. PostgreSQL Integration 验证完整 upgrade、约束和必要 downgrade。

无法安全确定 owner 时必须停止或让遗留资源保持不可访问，不得把资源静默分配给硬编码或
虚假用户。

必须继续遵守：

- 不修改 `20260901_0002` 或其他历史 Migration；
- 不使用 `create_all()`；
- Migration 只由 Alembic 管理；
- PostgreSQL Integration 验证唯一 head；
- Token 明文不得出现在 Migration、seed 或 fixture。

## 12. Security Boundary

### 凭据

- API Token 只存 hash；
- 使用独立服务器端 pepper；
- hash 比较必须 constant-time；
- Token 创建后只显示一次；
- Token 可撤销、可过期、可轮换；
- Provider API Key 与用户 API Token 必须使用不同配置和类型。

### 日志与审计

不得记录：

- Authorization Header；
- Token 明文或 hash；
- Cookie；
- Message content；
- Prompt；
- 完整 Response；
- SSE Chunk；
- Provider 原始响应或错误体；
- 数据库连接密码；
- 内部堆栈。

Audit 只记录通过 allowlist 的安全元数据。

### 资源隐藏

- 未认证请求返回 401；
- 已认证但缺少全局 capability 返回 403；
- Conversation 不存在或不属于当前 Actor 时统一返回 404。

统一 404 可以避免调用者通过状态码枚举其他用户资源。

### CORS

- 默认不允许任意 Origin；
- 显式配置允许的本地前端 Origin；
- 使用 Cookie 时不得配合通配 Origin；
- API Token Mode 也不应默认开放 `*`；
- CORS 不能作为认证机制。

### 部署边界

Trusted Local Mode 优先只绑定 loopback，不应暴露到公网。暴露到局域网必须有明确风险
确认。生产环境必须使用 API Token 和 HTTPS；TLS 可以由受信 Reverse Proxy 终止，但代理
必须覆盖客户端提供的身份 Header，只有受信代理地址可以提供 forwarded 信息。

`/ready` 不执行外部认证服务或 LLM 远程探活。

## 13. Error Mapping

| 内部错误 | HTTP 状态 | 对外行为 |
| --- | ---: | --- |
| Missing credential | 401 | 返回通用未认证消息 |
| Invalid token | 401 | 不说明 Token 是否存在 |
| Expired token | 401 | 返回通用凭据无效或过期消息 |
| Revoked token | 401 | 不暴露撤销时间 |
| Missing capability | 403 | 返回通用无权限消息 |
| Resource missing | 404 | 返回安全 not-found 响应 |
| Resource owned by another Actor | 404 | 与资源不存在统一处理 |
| Ownership mutation conflict | 409 | 返回安全冲突码 |
| Auth persistence unavailable | 503 | 不泄漏数据库或基础设施信息 |
| 未知认证错误 | 500 | 返回通用内部错误 |

401 响应可以包含标准 `WWW-Authenticate: Bearer`，但不得回显 Header 或 Token。

错误响应不得暴露：

- Token record ID、prefix 或 hash；
- User 是否存在；
- Conversation 实际 owner；
- SQL、表名或约束；
- 内部堆栈；
- Secret 配置；
- Provider 原始错误。

## 14. Testing Strategy

### Default Offline Tests

必须覆盖：

- ActorContext 不变量；
- Principal 类型规则；
- Trusted Local Mode 边界；
- Authorization 和 Ownership Policy；
- Token hash、过期、撤销和 constant-time validation；
- API dependency override；
- 401、403、404、409 和 503 错误映射；
- 未认证 Chat/Conversation 访问；
- 越权访问；
- 既有 Chat API JSON/SSE 回归；
- 既有 Conversation API 回归；
- 日志不含 Header、Token、Message 或 Prompt；
- Application import boundary；
- 无数据库、无 Docker、无真实 Key、无外部网络。

### PostgreSQL Integration Tests

必须覆盖：

- Migration 从 `20260901_0002` 升级到新 head；
- users、api_tokens 和 actor_audit_events schema；
- Token hash 持久化与 unique constraints；
- Token 撤销和过期查询；
- owner_user_id 外键和非空策略；
- Conversation 按 owner 查询；
- 遗留 Conversation 回填和无 owner fail-closed；
- Audit Event commit/rollback；
- Repository/UoW 事务边界；
- Migration graph 只有一个 head。

### Security Tests

必须覆盖：

- Token 明文不落库；
- Authorization Header 不进入日志或异常；
- Message、Prompt、Response 和 Chunk 不进入日志；
- 无认证访问被拒绝；
- Actor A 无法读取或修改 Actor B 的 Conversation；
- 禁用 User、撤销 Token 和过期 Token 被拒绝；
- `/health`、`/ready` 和 `/version` 保持设计语义；
- API Token Mode 缺少必要配置时启动失败；
- 不存在认证 fallback。

## 15. Phase 9 Step Plan

以下步骤是未来实施计划，本次不执行。

### Step 1：Identity and Actor Domain Design

- 目标：固化 Actor、Principal、User ID、Scope 和认证错误语义；
- 允许：纯 Python domain/value object 和离线单元测试；
- 禁止：API、ORM、Migration 和 Token Adapter；
- 验收：领域不变量稳定，无 FastAPI/SQLAlchemy 依赖；
- Runner：Default Offline CI 必须通过，PostgreSQL Runner 非必需。

### Step 2：Auth Persistence Schema Design

- 目标：建立 User、ApiToken、Audit 和 Conversation owner schema；
- 允许：在单独批准的实施步骤中新增 ORM、Alembic revision 和 Migration tests；
- 禁止：修改历史 Migration、使用 `create_all()` 或提前实施 API enforcement；
- 验收：唯一 head、upgrade/约束通过、无 Token 明文；
- Runner：Default Offline CI 和 PostgreSQL Integration CI 必须通过。

### Step 3：Authorization Policy and Ports

- 目标：实现 ActorContext、AuthorizationService、OwnershipPolicy 和 ports；
- 允许：Application policy、fake adapters 和离线测试；
- 禁止：Router 认证、SQLAlchemy 反向依赖和真实 Token 接入；
- 验收：策略集中、越权 fail closed、Application 保持框架无关；
- Runner：Default Offline CI 必须通过。

### Step 4：API Token Auth Implementation

- 目标：实现不透明 Token 验证和 ActorContext 注入；
- 允许：认证 Adapter、Token hashing、受控初始化命令和错误映射；
- 禁止：JWT、Session、OAuth、公共 Token 管理 API 和共享明文 Token；
- 验收：Token 只存 hash、缺配置 fail fast、401 契约稳定；
- Runner：Default Offline CI 和 PostgreSQL Integration CI 必须通过。

### Step 5：Conversation Ownership Enforcement

- 目标：让六个 Conversation endpoint 全部按 owner 隔离；
- 允许：owner 回填、新访问查询 port 和 Application policy wiring；
- 禁止：资源共享、多租户或修改 Chat/Provider DTO；
- 验收：跨 owner 访问返回安全 404，Conversation 创建和 owner 写入属于同一事务；
- Runner：Default Offline CI 和 PostgreSQL Integration CI 必须通过。

### Step 6：Security and Audit Boundary

- 目标：固化安全日志、审计、CORS 和 trusted deployment 边界；
- 允许：Audit Port/Adapter、安全过滤和部署配置验证；
- 禁止：保存敏感正文、引入 Redis 业务逻辑或外部审计服务；
- 验收：Secret hygiene tests、Audit allowlist 和生产配置 fail fast；
- Runner：Default Offline CI 和 PostgreSQL Integration CI 必须通过。

### Step 7：Testing / Release Gate Hardening

- 目标：增加认证、所有权、Migration 和冻结回归门禁；
- 允许：默认离线、PostgreSQL Integration 和静态架构扫描；
- 禁止：真实 LLM、外部网络和供应商账号；
- 验收：负向权限测试、Secret 扫描和 Phase 3–8 回归通过；
- Runner：Default Offline CI 和 PostgreSQL Integration CI 均必须通过。

### Step 8：Documentation / Freeze Review Preparation

- 目标：更新安全、API、部署、测试和 Release Gate 文档；
- 允许：文档和静态文档契约测试；
- 禁止：新增功能、创建 tag 或进入后续阶段；
- 验收：当前 commit 文档一致，Real LLM 为 Not Run、Cost 为 0；
- Runner：当前 commit 的两项 CI 均必须通过。

## 16. Entry Criteria

进入 Phase 9 implementation 前必须满足：

- 本架构设计已经独立审查通过；
- working tree clean；
- `v0.8.0` 保持不动；
- Default Offline CI 通过；
- PostgreSQL Integration CI 通过；
- Phase 3–8 冻结边界未破坏；
- 明确接受最小 User + 不透明 API Token 方案；
- 明确不采用 JWT 和 OAuth/OIDC；
- 明确接受 Trusted Local Mode 只作为受约束过渡模式；
- 明确接受 Conversation 单 owner 模型；
- 明确遗留 Conversation 的真实 owner 回填流程；
- 明确生产环境认证配置 fail fast；
- Real LLM 继续保持 Not Run；
- 不创建新 tag。

## 17. Freeze Criteria

Phase 9 Freeze 必须满足：

- Actor、Principal、User 和 Identity 语义稳定；
- API Token 认证边界稳定；
- Conversation ownership 全面生效；
- 未认证请求被拒绝；
- 越权请求被拒绝或安全隐藏；
- Chat 与 Conversation API 回归通过；
- Migration 从 `20260901_0002` 正确升级；
- Alembic 只有一个 head；
- Token 明文不落库；
- Authorization 和敏感正文不进入日志；
- Trusted Local 与生产模式边界明确；
- Default Offline CI 通过；
- PostgreSQL Integration CI 通过；
- Manual Real LLM 不运行；
- Real LLM Cost 为 `0`；
- 文档、Release Gate 和 Runner 证据一致；
- 独立 Freeze Review 通过；
- tag 只能在 Freeze Review 后由用户单独确认创建。

## 18. 禁止事项

Phase 9 架构设计和第一版 implementation 不得：

- 实现 Home Assistant；
- 实现 Agent；
- 实现 Tool Calling；
- 实现 RAG；
- 实现前端；
- 实现 WebSocket；
- 实现复杂多租户；
- 实现完整 RBAC；
- 实现 OAuth/OIDC；
- 实现 JWT；
- 修改历史 Migration；
- 使用 `create_all()`；
- 用虚假默认 User ID 伪装多用户；
- 静默分配历史 Conversation owner；
- 保存 Token 明文；
- 记录 Authorization Header；
- 记录 Message、Prompt、Response 或 Chunk；
- 修改 LLM Provider 公共契约；
- 让 Persistence 反向依赖 LLM；
- 运行真实 LLM；
- 配置真实 OpenAI/DeepSeek Key；
- 创建、移动或重建 tag；
- 未经单独批准进入 Phase 9 implementation。

## 是否建议进入 Phase 9 implementation

**当前不进入 implementation。**

ADR 0002 已正式接受以下核心决策：

1. 第一阶段采用最小 User + 数据库管理的不透明 API Token，不采用 JWT；
2. Trusted Local Mode 只用于受约束本地过渡部署，生产环境 fail fast；
3. Conversation 使用单一 `owner_user_id`，遗留数据只回填到安装者显式创建的真实 User。

Architecture Decision Acceptance 只完成了实施前的一项门禁。本次任务不授权 Step 1。
完成本次文档提交、确认当前 Runner 证据和 Entry Criteria 后，仍需用户单独指令才能开始
Phase 9 Step 1。
