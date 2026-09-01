# Conversation API

## Scope

Phase 8 Step 5 adds persistent, non-streaming conversation resources below
/api/v1/conversations. It does not change POST /api/v1/chat/completions: the
existing Chat JSON and SSE endpoints remain stateless and never read or write
conversation history.

The Conversation API currently exposes:

| Method | Path | Result |
|---|---|---|
| POST | /api/v1/conversations | Create a conversation |
| GET | /api/v1/conversations | List conversations with offset/limit pagination |
| GET | /api/v1/conversations/{conversation_id} | Read one conversation |
| GET | /api/v1/conversations/{conversation_id}/messages | Read ordered messages |
| POST | /api/v1/conversations/{conversation_id}/turns | Persist one non-streaming turn |
| POST | /api/v1/conversations/{conversation_id}/archive | Archive a conversation |

There is no persistent SSE endpoint. Create-turn requests accept only content and
an optional idempotency_key. They do not accept streaming, Provider selection,
model options, system messages, tool calls, user identity, or authentication data.

## Pagination

Conversation listing uses offset and limit. The response includes items, offset,
limit, and an optional next_offset. Message listing uses an optional
after_sequence cursor and limit; its response includes next_cursor.

Limits are validated at the HTTP boundary and cannot exceed 100. Conversation
context construction remains independently bounded by the Step 4 context builder.

## Turn result

A successful turn response contains the normalized user and final assistant
messages, conversation and turn identifiers, Provider and model names, finish
reason, normalized token usage, request identifier, and completed status. It does
not contain Provider request IDs, raw Provider payloads, HTTP objects, database
models, SQL text, Authorization headers, or API keys.

The API supports only a final non-streaming assistant message. Partial chunks are
neither returned by this endpoint nor persisted.

## Errors

- Missing conversation: 404 conversation_not_found.
- Archived conversation or idempotency conflict: 409.
- Invalid request data: 422 validation_error.
- Declared temporary persistence outage: 503.
- LLM failures: existing allowlisted safe LLM HTTP semantics.
- Unknown errors: the existing safe 500 handler.

Error mapping never copies raw exception text into the HTTP response. The router
depends only on Conversation application services; production dependency wiring
provides the SQLAlchemy Unit of Work adapter and the lifespan-owned LLMService.

## Offline verification

Default API contract tests replace all Conversation services with test doubles.
They require no PostgreSQL server, API key, Provider account, Docker daemon, or
external network. Real LLM integration remains explicit opt-in and was not run for
Step 5.
