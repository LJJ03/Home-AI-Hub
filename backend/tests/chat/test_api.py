"""Offline HTTP contract tests for non-streaming Chat completions."""

import ast
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import AsyncMock, Mock
from uuid import UUID

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.dependencies.chat import get_chat_service
from app.api.dependencies.database import get_database_manager
from app.api.router import api_router
from app.core.exceptions import register_exception_handlers
from app.llm import FinishReason, LLMRequest, LLMResponse, TokenUsage
from app.llm.service import LLMService
from app.schemas.chat import ChatFinishReason, ChatResponse, ChatUsage
from app.services import ChatService


CHAT_ROUTE_PATH = (
    Path(__file__).resolve().parents[2] / "app/api/v1/routes/chat.py"
)
CHAT_ENDPOINT = "/api/v1/chat/completions"


class _RecordingLLMService(LLMService):
    """Provide one normalized response without a Provider or network call."""

    def __init__(self) -> None:
        self.requests: list[LLMRequest] = []

    async def generate(self, request: LLMRequest) -> LLMResponse:
        self.requests.append(request)
        return LLMResponse(
            text="Offline answer",
            provider_name="contract-provider",
            model_name=request.model_name or "contract-model",
            finish_reason=FinishReason.STOP,
            usage=TokenUsage(
                input_tokens=3,
                output_tokens=2,
                total_tokens=5,
            ),
            provider_request_id="internal-provider-request-id",
        )


def _chat_payload(
    *,
    request_id: str | None = None,
    stream: bool | None = None,
) -> dict[str, object]:
    payload: dict[str, object] = {
        "messages": [{"role": "user", "content": "Hello"}],
    }
    if request_id is not None:
        payload["request_id"] = request_id
    if stream is not None:
        payload["stream"] = stream
    return payload


def _chat_response(*, request_id: str = "route-request-001") -> ChatResponse:
    return ChatResponse(
        answer="Application service answer",
        provider_name="contract-provider",
        model_name="contract-model",
        finish_reason=ChatFinishReason.STOP,
        usage=ChatUsage(input_tokens=4, output_tokens=3, total_tokens=7),
        request_id=request_id,
        created_at=datetime(2026, 8, 27, 8, 0, tzinfo=UTC),
    )


def _test_application(chat_service: object) -> tuple[FastAPI, AsyncMock]:
    application = FastAPI()
    register_exception_handlers(application)
    application.include_router(api_router)

    database_check = AsyncMock()
    database_manager = Mock()
    database_manager.check_connection = database_check
    application.dependency_overrides[get_chat_service] = lambda: chat_service
    application.dependency_overrides[get_database_manager] = lambda: database_manager
    return application, database_check


def test_non_streaming_chat_completion_returns_public_json_response() -> None:
    chat_service = Mock(spec=ChatService)
    chat_service.complete = AsyncMock(return_value=_chat_response())
    application, _ = _test_application(chat_service)

    with TestClient(application) as client:
        response = client.post(
            CHAT_ENDPOINT,
            json=_chat_payload(request_id="route-request-001", stream=False),
        )

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/json")
    assert response.json() == {
        "answer": "Application service answer",
        "provider_name": "contract-provider",
        "model_name": "contract-model",
        "finish_reason": "stop",
        "usage": {"input_tokens": 4, "output_tokens": 3, "total_tokens": 7},
        "request_id": "route-request-001",
        "created_at": "2026-08-27T08:00:00Z",
    }
    assert "provider_request_id" not in response.json()
    chat_service.complete.assert_awaited_once()
    received_request = chat_service.complete.await_args.args[0]
    assert received_request.stream is False


def test_missing_request_id_is_generated_by_chat_service() -> None:
    llm_service = _RecordingLLMService()
    application, _ = _test_application(ChatService(llm_service))

    with TestClient(application) as client:
        response = client.post(CHAT_ENDPOINT, json=_chat_payload())

    assert response.status_code == 200
    response_body = response.json()
    generated_id = UUID(response_body["request_id"])
    assert generated_id.version == 4
    assert generated_id.hex == response_body["request_id"]
    assert llm_service.requests[0].correlation_id == response_body["request_id"]
    assert llm_service.requests[0].messages[0].content == "Hello"


def test_custom_request_id_is_echoed_through_chat_service() -> None:
    llm_service = _RecordingLLMService()
    application, _ = _test_application(ChatService(llm_service))

    with TestClient(application) as client:
        response = client.post(
            CHAT_ENDPOINT,
            json=_chat_payload(request_id="client-request-123"),
        )

    assert response.status_code == 200
    assert response.json()["request_id"] == "client-request-123"
    assert llm_service.requests[0].correlation_id == "client-request-123"


@pytest.mark.parametrize(
    ("payload", "expected_stream"),
    (
        (_chat_payload(stream=False), False),
        (_chat_payload(), False),
    ),
    ids=("explicit-false", "default-false"),
)
def test_false_or_missing_stream_uses_non_streaming_service(
    payload: dict[str, object],
    expected_stream: bool,
) -> None:
    chat_service = Mock(spec=ChatService)
    chat_service.complete = AsyncMock(return_value=_chat_response())
    application, _ = _test_application(chat_service)

    with TestClient(application) as client:
        response = client.post(CHAT_ENDPOINT, json=payload)

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/json")
    request = chat_service.complete.await_args.args[0]
    assert request.stream is expected_stream


def test_invalid_chat_request_returns_422_without_calling_service() -> None:
    chat_service = Mock(spec=ChatService)
    chat_service.complete = AsyncMock(return_value=_chat_response())
    application, _ = _test_application(chat_service)

    with TestClient(application) as client:
        response = client.post(CHAT_ENDPOINT, json={"messages": []})

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"
    chat_service.complete.assert_not_awaited()


def test_system_endpoints_keep_existing_paths_and_semantics() -> None:
    chat_service = Mock(spec=ChatService)
    chat_service.complete = AsyncMock(return_value=_chat_response())
    application, database_check = _test_application(chat_service)

    with TestClient(application) as client:
        health_response = client.get("/health")
        ready_response = client.get("/ready")
        version_response = client.get("/version")

    assert health_response.status_code == 200
    assert health_response.json() == {"status": "ok"}
    assert ready_response.status_code == 200
    assert ready_response.json() == {"status": "ready"}
    assert version_response.status_code == 200
    assert version_response.json() == {"version": "0.1.0"}
    database_check.assert_awaited_once_with()
    chat_service.complete.assert_not_awaited()


def test_chat_router_respects_transport_layer_boundaries() -> None:
    syntax_tree = ast.parse(CHAT_ROUTE_PATH.read_text(encoding="utf-8"))
    imported_modules: set[str] = set()
    for node in ast.walk(syntax_tree):
        if isinstance(node, ast.Import):
            imported_modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module is not None:
            imported_modules.add(node.module)

    forbidden_prefixes = (
        "app.llm.service",
        "app.llm.providers",
        "app.llm.registry",
        "app.llm.factory",
        "app.llm.bootstrap",
        "app.db",
        "app.models",
        "app.repositories",
        "sqlalchemy",
        "redis",
        "pydantic_settings",
        "os",
        "httpx",
        "requests",
        "aiohttp",
        "socket",
        "websockets",
    )

    assert all(
        not module.startswith(forbidden_prefixes) for module in imported_modules
    )
    assert imported_modules == {
        "collections.abc",
        "datetime",
        "typing",
        "fastapi",
        "fastapi.responses",
        "app.api.dependencies.chat",
        "app.api.error_mapping.llm",
        "app.llm.exceptions",
        "app.schemas.chat",
        "app.services",
    }
