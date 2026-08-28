"""Unit tests for the stateless Chat application service."""

import ast
import asyncio
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

import pytest

from app.llm import (
    FinishReason,
    LLMException,
    LLMRequest,
    LLMResponse,
    MessageRole,
    ProviderTimeout,
    TokenUsage,
)
from app.llm.service import LLMService
from app.schemas.chat import (
    ChatFinishReason,
    ChatMessage,
    ChatMessageRole,
    ChatRequest,
    ChatUsage,
)
from app.services.chat import ChatService


SERVICE_MODULE_PATH = Path(__file__).resolve().parents[2] / "app/services/chat.py"


def _llm_response(*, usage: TokenUsage | None = None) -> LLMResponse:
    return LLMResponse(
        text="Normalized answer",
        provider_name="contract-provider",
        model_name="contract-model",
        finish_reason=FinishReason.LENGTH,
        usage=usage,
        provider_request_id="provider-internal-request-id",
    )


class _RecordingLLMService(LLMService):
    """Record generate calls without constructing or calling a Provider."""

    def __init__(
        self,
        response: LLMResponse,
        *,
        error: BaseException | None = None,
    ) -> None:
        self.requests: list[LLMRequest] = []
        self.response = response
        self.error = error

    async def generate(self, request: LLMRequest) -> LLMResponse:
        self.requests.append(request)
        if self.error is not None:
            raise self.error
        return self.response


def _chat_request(*, request_id: str | None = "chat-request-001") -> ChatRequest:
    return ChatRequest(
        messages=(
            ChatMessage(
                role=ChatMessageRole.USER,
                content="First question",
            ),
            ChatMessage(
                role=ChatMessageRole.ASSISTANT,
                content="Previous answer",
            ),
            ChatMessage(
                role=ChatMessageRole.USER,
                content="Follow-up question",
            ),
        ),
        model_name="requested-model",
        temperature=0.4,
        max_tokens=256,
        request_id=request_id,
    )


@pytest.mark.asyncio
async def test_complete_converts_chat_request_to_frozen_llm_request() -> None:
    llm_service = _RecordingLLMService(_llm_response())
    service = ChatService(llm_service)

    await service.complete(_chat_request())

    assert len(llm_service.requests) == 1
    llm_request = llm_service.requests[0]
    assert isinstance(llm_request, LLMRequest)
    assert tuple(message.role for message in llm_request.messages) == (
        MessageRole.USER,
        MessageRole.ASSISTANT,
        MessageRole.USER,
    )
    assert tuple(message.content for message in llm_request.messages) == (
        "First question",
        "Previous answer",
        "Follow-up question",
    )
    assert llm_request.model_name == "requested-model"
    assert llm_request.temperature == 0.4
    assert llm_request.max_tokens == 256
    assert llm_request.correlation_id == "chat-request-001"


@pytest.mark.asyncio
async def test_complete_generates_and_propagates_a_missing_request_id() -> None:
    llm_service = _RecordingLLMService(_llm_response())
    service = ChatService(llm_service)

    response = await service.complete(_chat_request(request_id=None))

    generated_id = UUID(response.request_id)
    assert generated_id.version == 4
    assert generated_id.hex == response.request_id
    assert llm_service.requests[0].correlation_id == response.request_id


@pytest.mark.asyncio
async def test_complete_converts_llm_response_to_independent_chat_response() -> None:
    llm_usage = TokenUsage(input_tokens=8, output_tokens=5, total_tokens=13)
    llm_service = _RecordingLLMService(_llm_response(usage=llm_usage))
    service = ChatService(llm_service)
    before = datetime.now(UTC)

    response = await service.complete(_chat_request())
    after = datetime.now(UTC)

    assert response.answer == "Normalized answer"
    assert response.provider_name == "contract-provider"
    assert response.model_name == "contract-model"
    assert response.finish_reason is ChatFinishReason.LENGTH
    assert response.usage == ChatUsage(
        input_tokens=8,
        output_tokens=5,
        total_tokens=13,
    )
    assert response.usage is not llm_usage
    assert response.request_id == "chat-request-001"
    assert before <= response.created_at <= after
    utc_offset = response.created_at.utcoffset()
    assert utc_offset is not None
    assert utc_offset.total_seconds() == 0
    assert "provider_request_id" not in response.model_dump()
    assert not hasattr(response, "provider_request_id")


@pytest.mark.asyncio
async def test_complete_preserves_absent_usage() -> None:
    service = ChatService(_RecordingLLMService(_llm_response()))

    response = await service.complete(_chat_request())

    assert response.usage is None


@pytest.mark.asyncio
async def test_chat_service_retains_no_request_or_history_state() -> None:
    llm_service = _RecordingLLMService(_llm_response())
    service = ChatService(llm_service)
    request = _chat_request(request_id=None)
    original_request = request.model_dump()

    first = await service.complete(request)
    second = await service.complete(request)

    assert ChatService.__slots__ == ("_llm_service",)
    assert not hasattr(service, "__dict__")
    assert request.model_dump() == original_request
    assert first.request_id != second.request_id
    assert len(llm_service.requests) == 2
    assert not hasattr(service, "messages")
    assert not hasattr(service, "history")
    assert not hasattr(service, "conversation_id")


@pytest.mark.asyncio
async def test_llm_exception_propagates_unchanged() -> None:
    error = ProviderTimeout(
        "Safe test timeout",
        provider_name="contract-provider",
    )
    llm_service = _RecordingLLMService(_llm_response(), error=error)
    service = ChatService(llm_service)

    with pytest.raises(LLMException) as raised:
        await service.complete(_chat_request())

    assert raised.value is error
    assert len(llm_service.requests) == 1


@pytest.mark.asyncio
async def test_cancelled_error_propagates_unchanged() -> None:
    cancellation = asyncio.CancelledError()
    llm_service = _RecordingLLMService(
        _llm_response(),
        error=cancellation,
    )
    service = ChatService(llm_service)

    with pytest.raises(asyncio.CancelledError) as raised:
        await service.complete(_chat_request())

    assert raised.value is cancellation
    assert len(llm_service.requests) == 1


def test_chat_service_module_respects_application_layer_boundaries() -> None:
    syntax_tree = ast.parse(SERVICE_MODULE_PATH.read_text(encoding="utf-8"))
    imported_modules: set[str] = set()
    for node in ast.walk(syntax_tree):
        if isinstance(node, ast.Import):
            imported_modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module is not None:
            imported_modules.add(node.module)

    forbidden_prefixes = (
        "fastapi",
        "starlette",
        "app.api",
        "app.db",
        "app.models",
        "app.repositories",
        "sqlalchemy",
        "redis",
        "app.llm.providers",
        "app.llm.registry",
        "app.llm.factory",
        "app.llm.bootstrap",
        "pydantic_settings",
        "os",
        "httpx",
        "requests",
        "aiohttp",
        "socket",
    )

    assert all(
        not module.startswith(forbidden_prefixes) for module in imported_modules
    )
