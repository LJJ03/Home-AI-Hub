# Conversation Application Layer

## Status and scope

This document records Phase 8 Implementation Step 4 only. The application layer
implements conversation commands, queries, bounded context construction, and
non-streaming persistent chat orchestration. It does not add an HTTP endpoint or
change the Phase 5 stateless Chat Completions JSON/SSE contract.

Phase 8 Step 5 adds a separate HTTP boundary documented in
docs/api/conversations.md without changing these application contracts or the
Phase 5 stateless Chat API. Phase 8 Step 6 hardens offline, integration, API,
architecture, and documentation quality gates without changing application
behavior. Real LLM integration was not run and the provider cost for these steps
is zero. Phase 8 is not frozen.

## Application boundaries

- ConversationCommandService creates and archives conversations through
  ConversationUnitOfWork. It never calls an LLM.
- ConversationQueryService returns immutable application DTOs for conversation
  and message queries. ORM models and sessions do not cross this boundary.
- ConversationContextBuilder converts a bounded suffix of completed
  user/assistant messages plus the current user message into an LLMRequest.
  Its default history limit is 20 messages and its default character budget is
  32,000 characters.
- ConversationChatService depends on the application Unit of Work protocol and
  a minimal application-facing generate(LLMRequest) LLM port. It does not know
  Provider adapters, Registry, Factory, Bootstrap, HTTPX, or provider JSON.

The context builder does not perform summarization, RAG, embedding, Provider
routing, or HTTP work. Pending, failed, and cancelled turns are excluded by the
completed-history repository query. No streaming chunk is persisted.

## Transaction sequence

Persistent non-streaming chat uses three isolated phases:

1. Lock the conversation, create the pending turn and user message, then commit.
2. Load bounded completed history in a short read transaction, close it, and call
   the LLM with no active database transaction.
3. Lock the conversation again, persist the final assistant message and normalized
   completion metadata, mark the turn completed, then commit.

An LLM failure opens an independent short transaction to mark the turn failed with
only a safe error code. Cancellation is propagated after a best-effort independent
transaction marks the turn cancelled. There is no automatic retry, fallback, or
Provider routing.

## Security and testing

Commands, message DTOs, and chat results redact message content from their
representations. The application layer does not log message content and does not
persist raw Provider exceptions, request/response objects, Provider request IDs,
Authorization headers, prompts, complete raw responses, or chunk sequences.

Default tests use test-only in-memory repositories, Unit of Work objects, and an
LLM fake. They require no PostgreSQL instance, API key, Provider account, Docker
daemon, or external network. PostgreSQL integration and real LLM integration
remain explicit opt-in paths.

Step 6 also collects a PostgreSQL-backed production-wiring API test. It remains
behind `--run-integration` and uses only MockProvider; it never authorizes real LLM
network access. Cross-layer AST gates keep Domain and Application independent of
infrastructure, prevent Provider reverse dependencies, and preserve the original
stateless Chat Completions contract.
