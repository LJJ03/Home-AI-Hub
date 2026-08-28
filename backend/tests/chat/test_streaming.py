"""Offline SSE contract, failure, cancellation, and cleanup tests."""

import ast
import asyncio
import json
from collections.abc import AsyncIterator
from pathlib import Path
from typing import cast
from uuid import UUID

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.dependencies.chat import get_chat_service
from app.api.router import api_router
from app.api.v1.routes.chat import _create_streaming_response
from app.core.exceptions import register_exception_handlers
from app.llm import (
    FinishReason,
    LLMRequest,
    LLMStreamChunk,
    ProviderRateLimitError,
    TokenUsage,
)
from app.llm.providers.mock import MockErrorMode, MockProvider
from app.llm.service import LLMService
from app.schemas.chat import ChatMessage, ChatMessageRole, ChatRequest
from app.services import ChatService


CHAT_ENDPOINT = "/api/v1/chat/completions"
CHAT_ROUTE_PATH = (
    Path(__file__).resolve().parents[2] / "app/api/v1/routes/chat.py"
)
CHAT_SERVICE_PATH = Path(__file__).resolve().parents[2] / "app/services/chat.py"
SENSITIVE_VALUES = (
    "sk-stream-secret",
    "Complete private prompt",
    "Complete private model response",
    "VendorSDKStreamingException",
    "provider-stream-request-secret",
)


def _chat_payload(*, request_id: str | None = None) -> dict[str, object]:
    payload: dict[str, object] = {
        "messages": [{"role": "user", "content": "Stream this response"}],
        "stream": True,
    }
    if request_id is not None:
        payload["request_id"] = request_id
    return payload


def _chat_request(*, request_id: str = "cancel-request-001") -> ChatRequest:
    return ChatRequest(
        messages=(
            ChatMessage(
                role=ChatMessageRole.USER,
                content="Stream this response",
            ),
        ),
        stream=True,
        request_id=request_id,
    )


def _test_application(chat_service: ChatService) -> FastAPI:
    application = FastAPI()
    register_exception_handlers(application)
    application.include_router(api_router)
    application.dependency_overrides[get_chat_service] = lambda: chat_service
    return application


def _parse_sse(payload: str) -> list[tuple[str, dict[str, object]]]:
    parsed: list[tuple[str, dict[str, object]]] = []
    for block in payload.strip().split("\n\n"):
        lines = block.splitlines()
        assert len(lines) == 2
        assert lines[0].startswith("event: ")
        assert lines[1].startswith("data: ")
        event_name = lines[0].removeprefix("event: ")
        event_data = json.loads(lines[1].removeprefix("data: "))
        assert event_data["event"] == event_name
        parsed.append((event_name, event_data))
    return parsed


class _TrackingStream(AsyncIterator[LLMStreamChunk]):
    """Yield chunks or normalized failures with observable cleanup."""

    def __init__(
        self,
        items: tuple[LLMStreamChunk | BaseException, ...],
    ) -> None:
        self._items = iter(items)
        self.aclose_calls = 0

    def __aiter__(self) -> AsyncIterator[LLMStreamChunk]:
        return self

    async def __anext__(self) -> LLMStreamChunk:
        try:
            item = next(self._items)
        except StopIteration as exception:
            raise StopAsyncIteration from exception
        if isinstance(item, BaseException):
            raise item
        return item

    async def aclose(self) -> None:
        self.aclose_calls += 1


class _BlockingAfterFirstStream(AsyncIterator[LLMStreamChunk]):
    """Yield once, then block until the downstream consumer is cancelled."""

    def __init__(self) -> None:
        self._yielded_first = False
        self.blocked = asyncio.Event()
        self.aclose_calls = 0

    def __aiter__(self) -> AsyncIterator[LLMStreamChunk]:
        return self

    async def __anext__(self) -> LLMStreamChunk:
        if not self._yielded_first:
            self._yielded_first = True
            return LLMStreamChunk(
                sequence=0,
                delta="first",
                provider_name="blocking-provider",
                model_name="blocking-model",
            )
        self.blocked.set()
        await asyncio.Event().wait()
        raise StopAsyncIteration

    async def aclose(self) -> None:
        self.aclose_calls += 1


class _StreamingLLMService(LLMService):
    """Expose an injected stream without constructing a concrete Provider."""

    def __init__(self, stream: AsyncIterator[LLMStreamChunk]) -> None:
        self.stream = stream
        self.requests: list[LLMRequest] = []

    def stream_generate(self, request: LLMRequest) -> AsyncIterator[LLMStreamChunk]:
        self.requests.append(request)
        return self.stream


def test_streaming_mock_response_uses_ordered_sse_events() -> None:
    provider = MockProvider(
        response_text="abcdefghijk",
        default_model="stream-model",
    )
    application = _test_application(ChatService(LLMService(provider)))

    with TestClient(application) as client:
        with client.stream("POST", CHAT_ENDPOINT, json=_chat_payload()) as response:
            response_text = "".join(response.iter_text())

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert response.headers["cache-control"] == "no-cache"
    events = _parse_sse(response_text)
    assert [event_name for event_name, _ in events] == ["chunk", "chunk", "done"]
    assert [event["delta"] for _, event in events[:-1]] == ["abcdefgh", "ijk"]
    assert [event["sequence"] for _, event in events] == [0, 1, 2]

    request_ids = {cast(str, event["request_id"]) for _, event in events}
    assert len(request_ids) == 1
    generated_request_id = request_ids.pop()
    generated_uuid = UUID(generated_request_id)
    assert generated_uuid.version == 4
    assert generated_uuid.hex == generated_request_id

    for _, event in events[:-1]:
        assert event["provider_name"] == "mock"
        assert event["model_name"] == "stream-model"
        assert set(event) == {
            "event",
            "request_id",
            "sequence",
            "delta",
            "provider_name",
            "model_name",
            "created_at",
        }
    done = events[-1][1]
    assert done["finish_reason"] == "stop"
    assert done["usage"] is None
    assert "provider_request_id" not in response_text
    assert len(provider.recorded_requests) == 1
    assert provider.recorded_requests[0].correlation_id == generated_request_id


def test_empty_mock_response_still_emits_done_event() -> None:
    provider = MockProvider(response_text="", default_model="empty-model")
    application = _test_application(ChatService(LLMService(provider)))

    with TestClient(application) as client:
        response = client.post(
            CHAT_ENDPOINT,
            json=_chat_payload(request_id="empty-request-001"),
        )

    assert response.status_code == 200
    events = _parse_sse(response.text)
    assert [event_name for event_name, _ in events] == ["done"]
    assert events[0][1]["sequence"] == 0
    assert events[0][1]["finish_reason"] == "stop"
    assert events[0][1]["request_id"] == "empty-request-001"


def test_done_event_contains_normalized_usage() -> None:
    upstream = _TrackingStream(
        (
            LLMStreamChunk(
                sequence=0,
                provider_name="usage-provider",
                model_name="usage-model",
                is_final=True,
                finish_reason=FinishReason.LENGTH,
                usage=TokenUsage(
                    input_tokens=5,
                    output_tokens=7,
                    total_tokens=12,
                ),
                provider_request_id="private-provider-request",
            ),
        )
    )
    service = ChatService(_StreamingLLMService(upstream))
    application = _test_application(service)

    with TestClient(application) as client:
        response = client.post(
            CHAT_ENDPOINT,
            json=_chat_payload(request_id="usage-request-001"),
        )

    events = _parse_sse(response.text)
    assert events == [
        (
            "done",
            {
                "created_at": events[0][1]["created_at"],
                "event": "done",
                "request_id": "usage-request-001",
                "sequence": 0,
                "provider_name": "usage-provider",
                "model_name": "usage-model",
                "finish_reason": "length",
                "usage": {
                    "input_tokens": 5,
                    "output_tokens": 7,
                    "total_tokens": 12,
                },
            },
        )
    ]
    assert "private-provider-request" not in response.text
    assert upstream.aclose_calls == 1


def test_error_before_first_event_uses_normal_http_mapping() -> None:
    provider = MockProvider(
        error_mode=MockErrorMode.TIMEOUT,
        default_model="failing-model",
    )
    application = _test_application(ChatService(LLMService(provider)))

    with TestClient(application) as client:
        response = client.post(
            CHAT_ENDPOINT,
            json=_chat_payload(request_id="prefetch-request-001"),
        )

    assert response.status_code == 504
    assert response.headers["content-type"].startswith("application/json")
    assert response.json() == {
        "error": {
            "code": "llm_provider_timeout",
            "message": "LLM provider timed out",
            "details": {"request_id": "prefetch-request-001"},
        }
    }
    assert "mock-request" not in response.text


def test_error_after_first_event_emits_safe_sse_error_and_closes() -> None:
    sensitive_error = ProviderRateLimitError(
        " | ".join(SENSITIVE_VALUES[:3]),
        provider_name="private-provider",
        provider_request_id=SENSITIVE_VALUES[4],
        retry_after_seconds=4.0,
    )
    sensitive_error.__cause__ = RuntimeError(SENSITIVE_VALUES[3])
    upstream = _TrackingStream(
        (
            LLMStreamChunk(
                sequence=0,
                delta="visible",
                provider_name="contract-provider",
                model_name="contract-model",
            ),
            sensitive_error,
        )
    )
    application = _test_application(
        ChatService(_StreamingLLMService(upstream))
    )

    with TestClient(application) as client:
        response = client.post(
            CHAT_ENDPOINT,
            json=_chat_payload(request_id="midstream-request-001"),
        )

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    events = _parse_sse(response.text)
    assert [event_name for event_name, _ in events] == ["chunk", "error"]
    assert events[0][1]["delta"] == "visible"
    assert events[1][1] == {
        "created_at": events[1][1]["created_at"],
        "event": "error",
        "request_id": "midstream-request-001",
        "code": "llm_rate_limited",
        "message": "LLM request was rate limited",
        "retry_after_seconds": 4.0,
    }
    for sensitive_value in SENSITIVE_VALUES:
        assert sensitive_value not in response.text
    assert "provider_request_id" not in response.text
    assert upstream.aclose_calls == 1


@pytest.mark.asyncio
async def test_downstream_cancellation_propagates_and_closes_upstream() -> None:
    upstream = _BlockingAfterFirstStream()
    llm_service = _StreamingLLMService(upstream)
    chat_service = ChatService(llm_service)
    response = await _create_streaming_response(
        _chat_request(),
        chat_service,
    )
    body = cast(AsyncIterator[bytes], response.body_iterator)

    first_payload = await anext(body)
    assert first_payload.startswith(b"event: chunk\n")
    consumer = asyncio.create_task(anext(body))
    await upstream.blocked.wait()
    consumer.cancel()

    with pytest.raises(asyncio.CancelledError):
        await consumer

    assert upstream.aclose_calls == 1
    assert llm_service.requests[0].correlation_id == "cancel-request-001"


def test_streaming_modules_do_not_cross_frozen_boundaries() -> None:
    imported_modules: set[str] = set()
    source_texts: list[str] = []
    for source_path in (CHAT_ROUTE_PATH, CHAT_SERVICE_PATH):
        source_text = source_path.read_text(encoding="utf-8")
        source_texts.append(source_text)
        syntax_tree = ast.parse(source_text)
        for node in ast.walk(syntax_tree):
            if isinstance(node, ast.Import):
                imported_modules.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module is not None:
                imported_modules.add(node.module)

    forbidden_prefixes = (
        "app.llm.providers",
        "app.llm.registry",
        "app.llm.factory",
        "app.llm.bootstrap",
        "app.db",
        "app.models",
        "app.repositories",
        "sqlalchemy",
        "redis",
        "httpx",
        "requests",
        "aiohttp",
        "socket",
        "websockets",
    )
    combined_source = "\n".join(source_texts)

    assert all(
        not module.startswith(forbidden_prefixes) for module in imported_modules
    )
    assert "WebSocket" not in combined_source
    assert "logging" not in imported_modules
    assert "provider_request_id" not in combined_source
    assert "conversation_id" not in combined_source
