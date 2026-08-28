# Chat API 使用说明

## Endpoint

```text
POST /api/v1/chat/completions
Content-Type: application/json
```

该端点提供一次无状态 Chat Completion。`stream` 缺失或为 `false` 时返回 JSON；
`stream=true` 时返回 Server-Sent Events（SSE）。当前默认 Provider 为离线 `mock`，
不需要 API Key，也不访问外部网络。

Phase 6 已新增 DeepSeek 和 OpenAI Adapter，但没有改变本端点。Provider 由服务端
`LLM_PROVIDER` 配置选择，客户端不能通过 Request 切换供应商；`model_name` 只是在当前
已选 Provider 内请求模型，不是 Provider routing。无论后端选择 `mock`、`deepseek` 还是
`openai`，客户端观察到的 Chat JSON、SSE 和错误契约保持一致。

## Request

### 最小请求

```json
{
  "messages": [
    {
      "role": "user",
      "content": "请用一句话介绍 Home AI Hub。"
    }
  ]
}
```

### 完整非流式请求

```json
{
  "messages": [
    {
      "role": "user",
      "content": "我想控制客厅灯。"
    },
    {
      "role": "assistant",
      "content": "你希望调整亮度还是开关状态？"
    },
    {
      "role": "user",
      "content": "只解释可以如何描述需求，不要执行任何设备操作。"
    }
  ],
  "model_name": "mock-model",
  "temperature": 0.7,
  "max_tokens": 256,
  "stream": false,
  "request_id": "client-request-001"
}
```

### 字段

| 字段 | 必需 | 规则 | 语义 |
| --- | --- | --- | --- |
| `messages` | 是 | 至少一条；至少一条 `user`；最后一条必须是 `user` | 本次请求携带的临时上下文 |
| `messages[].role` | 是 | 只允许 `user`、`assistant` | 消息在本次输入中的角色 |
| `messages[].content` | 是 | 字符串；非空且不能全为空白 | 消息正文 |
| `model_name` | 否 | 1–255 个非空字符 | 请求指定模型；缺失时使用 LLM 默认模型 |
| `temperature` | 否 | 数字，`0..2` | 本次生成温度 |
| `max_tokens` | 否 | 正整数 | 本次生成 token 上限 |
| `stream` | 否 | 严格布尔值，默认 `false` | 选择 JSON 或 SSE |
| `request_id` | 否 | 1–128 字符，首字符为字母或数字；可用 `._:-` | 单次请求关联 ID |

角色不要求严格 `user/assistant` 交替，便于客户端提交临时上下文；但最后一条必须是
`user`，以明确本次需要回答的输入。

所有未知字段都会返回 422。当前明确不接受 `conversation_id`、`user_id`、
`session_id`、`system_prompt`、tools、functions、metadata、`extra_kwargs`、
`provider_options` 或 `vendor_options`。

### `request_id` 语义

`request_id` 只关联一次 HTTP/LLM 调用。客户端传入时，成功响应和该流的所有事件都会
回显；缺失时，ChatService 为本次调用生成一个值。它不是 conversation、session、user
或持久化实体 ID。若希望在失败响应中稳定获得该 ID，客户端应在请求中显式提供。

### 为什么没有 `conversation_id`

Phase 5 的端点刻意保持无状态。服务器不加载或保存历史，`messages` 只在当前请求处理
期间使用。有状态聊天将在未来通过新增 Conversation Service、Repository Protocol 和
新增接口实现，不会改变当前 completions 语义。

### 为什么不允许客户端 `system` role

系统策略、安全约束和产品指令属于可信的服务端编排边界。当前阶段尚未实现该编排，
因此不允许客户端伪装为 `system` 消息。未来服务端可在独立上层模块中加入策略，而不
需要向公共 Request 开放该角色。

## 非流式 Response

`stream` 缺失或为 `false` 时返回 `200 application/json`：

```json
{
  "answer": "Mock response",
  "provider_name": "mock",
  "model_name": "mock-model",
  "finish_reason": "stop",
  "usage": {
    "input_tokens": 12,
    "output_tokens": 3,
    "total_tokens": 15
  },
  "request_id": "client-request-001",
  "created_at": "2026-08-27T00:00:00Z"
}
```

`usage` 在上游未提供 token 数时可以为 `null`。`created_at` 是服务端生成的 UTC 时间。
响应不包含 `provider_request_id`、LLM 原始对象、SDK response/usage 或供应商错误。

## SSE Streaming

设置 `stream=true`：

```bash
curl -N -X POST http://localhost:8000/api/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"messages":[{"role":"user","content":"请流式回答。"}],"stream":true,"request_id":"stream-001"}'
```

成功响应为：

```text
HTTP/1.1 200 OK
Content-Type: text/event-stream; charset=utf-8
Cache-Control: no-cache
X-Accel-Buffering: no
```

每个 SSE 帧包含一个 `event` 行、一个 JSON `data` 行和一个空行。

### `chunk` event

```text
event: chunk
data: {"event":"chunk","request_id":"stream-001","sequence":0,"delta":"Mock res","provider_name":"mock","model_name":"mock-model","created_at":"2026-08-27T00:00:00Z"}

```

`sequence` 从非负整数开始并表达顺序；`delta` 可以为空字符串。客户端应按事件顺序增量
展示，不应假设每个 Chunk 的字符数。

### `done` event

```text
event: done
data: {"event":"done","request_id":"stream-001","sequence":2,"provider_name":"mock","model_name":"mock-model","finish_reason":"stop","usage":null,"created_at":"2026-08-27T00:00:01Z"}

```

`done` 表示成功完成，并携带标准 finish reason 与可选 usage。即使模型生成空文本，流
仍会发送 `done`。客户端收到 `done` 后应停止等待更多内容。

### `error` event

```text
event: error
data: {"event":"error","request_id":"stream-001","code":"llm_provider_timeout","message":"LLM provider timed out","retry_after_seconds":null,"created_at":"2026-08-27T00:00:01Z"}

```

`error` 只用于 HTTP 响应已经开始后的失败。它只包含固定安全文案和最小关联信息，发送
后流会结束。不得把 `message` 当作供应商诊断内容。

### 流开始前与开始后错误

服务器会在发送响应头前预取第一个事件：

- 首事件产生前失败：返回普通 JSON HTTP 错误及对应状态码；
- 首事件发送后失败：HTTP 状态不能再修改，发送安全 `error` SSE Event 后关闭流。

因此客户端必须同时处理非 2xx JSON 错误和 200 SSE 中的 `error` Event。

### 取消与断开

客户端关闭连接时，取消会传播到 ChatService、LLMService 和 Provider 流，上游异步
迭代器会被关闭。服务器不会为了流式传输缓存完整 Prompt、完整响应或完整 Chunk 序列。

本接口使用 SSE 而不是 WebSocket，因为当前交互是一次 POST 对应单向生成事件流；SSE
已满足顺序传输、代理兼容和断开取消，不需要双向会话状态。

## HTTP 错误

统一错误体沿用应用现有结构：

```json
{
  "error": {
    "code": "llm_provider_timeout",
    "message": "LLM provider timed out",
    "details": {
      "request_id": "client-request-001"
    }
  }
}
```

| 场景 | HTTP | `error.code` |
| --- | ---: | --- |
| Provider 配置非法 | 500 | `llm_configuration_error` |
| 配置的 Provider 未注册 | 500 | `llm_provider_not_registered` |
| Provider 认证失败 | 502 | `llm_provider_authentication_failed` |
| Provider 限流 | 429 | `llm_rate_limited` |
| Provider 超时 | 504 | `llm_provider_timeout` |
| Provider 不可用 | 503 | `llm_provider_unavailable` |
| Provider 响应不符合契约 | 502 | `llm_invalid_response` |
| 其他已知 LLM 错误 | 502 | `llm_provider_error` |
| Request Schema 校验失败 | 422 | 沿用应用校验错误码 |
| 未知服务器错误 | 500 | 沿用应用安全 500 错误码 |

限流错误可在 details 中额外返回已校验的 `retry_after_seconds`。任何错误都不会返回
API Key、Prompt、完整响应、供应商 HTTP 错误、SDK Exception、异常 cause 或
`provider_request_id`。

## Provider 与运行限制

当前 Bootstrap 显式注册：

```text
LLM_PROVIDER=mock      -> MockProvider
LLM_PROVIDER=deepseek  -> DeepSeekProvider
LLM_PROVIDER=openai    -> OpenAIProvider
```

`mock` 无密钥、零网络；真实 Provider 需要各自 API Key、HTTPS Base URL 和默认模型。
配置失败或未注册名称会使应用启动 fail fast，不会自动切换、回退、路由或降级。

Chat Router 和 ChatService 不知道具体 Provider。真实 Provider 只在冻结 LLMService 下方
处理 HTTP/SSE 和供应商 JSON，再输出统一 LLM DTO；ChatService 将其复制为独立 Chat
DTO。因此真实接入不会暴露 `provider_request_id`、Authorization Header、原始 HTTP
Response、供应商 JSON 或异常。

`/ready` 仍只检查应用和 PostgreSQL，不远程调用模型。前端、语音终端和未来 Home
Assistant 上层模块应调用本稳定 API，不应直接依赖具体 Provider。

Phase 6 的代码和静态门禁已完成，但正式默认 pytest 尚未在项目 Python 3.13 环境执行
成功；当前状态为 **Phase 6 Freeze Pending / 待正式 pytest 验证**。部署配置与测试说明
分别见 [LLM Provider 运维指南](../operations/llm-providers.md) 和
[LLM Integration 测试指南](../testing/llm-integration.md)。
