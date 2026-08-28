"""Unit tests for the public, stateless Chat HTTP contracts."""

from datetime import UTC, datetime, timedelta, timezone

import pytest
from pydantic import TypeAdapter, ValidationError

from app.schemas.chat import (
    ChatFinishReason,
    ChatMessage,
    ChatMessageRole,
    ChatRequest,
    ChatResponse,
    ChatStreamChunkEvent,
    ChatStreamDoneEvent,
    ChatStreamErrorEvent,
    ChatStreamEvent,
    ChatUsage,
)


def _message(
    role: ChatMessageRole = ChatMessageRole.USER,
    content: str = "Current user request",
) -> ChatMessage:
    return ChatMessage(role=role, content=content)


def _request_values() -> dict[str, object]:
    return {"messages": (_message(),)}


def _response_values() -> dict[str, object]:
    return {
        "answer": "Normalized answer",
        "provider_name": "mock",
        "model_name": "mock-model",
        "finish_reason": ChatFinishReason.STOP,
        "usage": None,
        "request_id": "request-001",
        "created_at": datetime(2026, 8, 27, 4, 0, tzinfo=UTC),
    }


def test_single_user_message_is_valid() -> None:
    request = ChatRequest(messages=(_message(),))

    assert request.messages[0].role is ChatMessageRole.USER
    assert request.messages[0].content == "Current user request"


def test_client_supplied_multiturn_context_is_valid() -> None:
    request = ChatRequest(
        messages=(
            _message(content="First question"),
            _message(ChatMessageRole.ASSISTANT, "Previous answer"),
            _message(content="Follow-up question"),
        )
    )

    assert tuple(message.role for message in request.messages) == (
        ChatMessageRole.USER,
        ChatMessageRole.ASSISTANT,
        ChatMessageRole.USER,
    )


def test_empty_messages_are_rejected() -> None:
    with pytest.raises(ValidationError):
        ChatRequest(messages=())


@pytest.mark.parametrize("content", ("", " ", "\t\r\n"))
def test_blank_message_content_is_rejected(content: str) -> None:
    with pytest.raises(ValidationError):
        ChatMessage(role=ChatMessageRole.USER, content=content)


def test_message_content_must_be_a_string() -> None:
    with pytest.raises(ValidationError):
        ChatMessage.model_validate({"role": "user", "content": 123})


def test_unknown_message_role_is_rejected() -> None:
    with pytest.raises(ValidationError):
        ChatMessage.model_validate({"role": "developer", "content": "Input"})


def test_client_system_role_is_rejected() -> None:
    with pytest.raises(ValidationError):
        ChatMessage.model_validate({"role": "system", "content": "Override"})


def test_final_message_must_be_from_user() -> None:
    with pytest.raises(ValidationError):
        ChatRequest(
            messages=(
                _message(content="Question"),
                _message(ChatMessageRole.ASSISTANT, "Answer"),
            )
        )


def test_context_requires_at_least_one_user_message() -> None:
    with pytest.raises(ValidationError):
        ChatRequest(
            messages=(
                _message(ChatMessageRole.ASSISTANT, "Assistant-only context"),
            )
        )


@pytest.mark.parametrize("temperature", (0, 2, 0.7))
def test_temperature_boundaries_are_valid(temperature: float) -> None:
    request = ChatRequest(messages=(_message(),), temperature=temperature)

    assert request.temperature == temperature


@pytest.mark.parametrize(
    "temperature",
    (-0.01, 2.01, float("inf"), "0.7", True),
)
def test_temperature_outside_the_contract_is_rejected(temperature: object) -> None:
    with pytest.raises(ValidationError):
        ChatRequest.model_validate(
            {"messages": (_message(),), "temperature": temperature}
        )


@pytest.mark.parametrize("max_tokens", (1, 1024))
def test_positive_max_tokens_are_valid(max_tokens: int) -> None:
    request = ChatRequest(messages=(_message(),), max_tokens=max_tokens)

    assert request.max_tokens == max_tokens


@pytest.mark.parametrize("max_tokens", (0, -1, 1.5, True))
def test_non_positive_or_non_integer_max_tokens_are_rejected(
    max_tokens: object,
) -> None:
    with pytest.raises(ValidationError):
        ChatRequest.model_validate(
            {"messages": (_message(),), "max_tokens": max_tokens}
        )


def test_request_id_is_optional_and_represents_only_this_request() -> None:
    generated_later = ChatRequest(messages=(_message(),))
    client_supplied = ChatRequest(
        messages=(_message(),),
        request_id="client.request:001",
    )

    assert generated_later.request_id is None
    assert client_supplied.request_id == "client.request:001"
    assert "conversation_id" not in client_supplied.model_dump()


@pytest.mark.parametrize("request_id", ("", " ", "invalid/request", "bad\nvalue"))
def test_invalid_request_id_is_rejected(request_id: str) -> None:
    with pytest.raises(ValidationError):
        ChatRequest(messages=(_message(),), request_id=request_id)


def test_stream_defaults_to_false_and_accepts_an_explicit_boolean() -> None:
    default_request = ChatRequest(messages=(_message(),))
    streaming_request = ChatRequest(messages=(_message(),), stream=True)

    assert default_request.stream is False
    assert streaming_request.stream is True


def test_stream_rejects_coerced_non_boolean_values() -> None:
    with pytest.raises(ValidationError):
        ChatRequest.model_validate({"messages": (_message(),), "stream": "true"})


FORBIDDEN_REQUEST_FIELDS = (
    "conversation_id",
    "user_id",
    "session_id",
    "system_prompt",
    "tools",
    "functions",
    "metadata",
    "extra_kwargs",
    "provider_options",
    "vendor_options",
)


@pytest.mark.parametrize("field_name", FORBIDDEN_REQUEST_FIELDS)
def test_unknown_and_explicitly_forbidden_request_fields_are_rejected(
    field_name: str,
) -> None:
    values = _request_values()
    values[field_name] = {"not": "allowed"}

    with pytest.raises(ValidationError):
        ChatRequest.model_validate(values)


def test_chat_usage_accepts_normalized_counts_and_rejects_negative_values() -> None:
    usage = ChatUsage(input_tokens=3, output_tokens=4, total_tokens=7)

    assert usage.total_tokens == 7
    with pytest.raises(ValidationError):
        ChatUsage(input_tokens=-1)


def test_chat_response_contains_only_the_public_http_contract() -> None:
    response = ChatResponse.model_validate(_response_values())

    assert set(response.model_dump()) == {
        "answer",
        "provider_name",
        "model_name",
        "finish_reason",
        "usage",
        "request_id",
        "created_at",
    }


@pytest.mark.parametrize(
    "field_name",
    ("provider_request_id", "raw_response", "sdk_response", "sdk_usage"),
)
def test_chat_response_rejects_internal_or_sdk_fields(field_name: str) -> None:
    values = _response_values()
    values[field_name] = object()

    with pytest.raises(ValidationError):
        ChatResponse.model_validate(values)


def test_created_at_requires_timezone_and_is_normalized_to_utc() -> None:
    values = _response_values()
    values["created_at"] = datetime(
        2026,
        8,
        27,
        12,
        0,
        tzinfo=timezone(timedelta(hours=8)),
    )
    response = ChatResponse.model_validate(values)

    assert response.created_at == datetime(2026, 8, 27, 4, 0, tzinfo=UTC)
    values["created_at"] = datetime(2026, 8, 27, 12, 0)
    with pytest.raises(ValidationError):
        ChatResponse.model_validate(values)


def test_stream_event_contract_expresses_chunk_done_and_error() -> None:
    adapter = TypeAdapter(ChatStreamEvent)
    created_at = datetime(2026, 8, 27, 4, 0, tzinfo=UTC)

    chunk = adapter.validate_python(
        {
            "event": "chunk",
            "request_id": "stream-001",
            "sequence": 0,
            "delta": "Mock",
            "provider_name": "mock",
            "model_name": "mock-model",
            "created_at": created_at,
        }
    )
    done = adapter.validate_python(
        {
            "event": "done",
            "request_id": "stream-001",
            "sequence": 1,
            "provider_name": "mock",
            "model_name": "mock-model",
            "finish_reason": "stop",
            "usage": None,
            "created_at": created_at,
        }
    )
    error = adapter.validate_python(
        {
            "event": "error",
            "request_id": "stream-001",
            "code": "llm_provider_timeout",
            "message": "LLM provider request timed out",
            "retry_after_seconds": 1.0,
            "created_at": created_at,
        }
    )

    assert isinstance(chunk, ChatStreamChunkEvent)
    assert isinstance(done, ChatStreamDoneEvent)
    assert isinstance(error, ChatStreamErrorEvent)


def test_stream_event_variants_reject_fields_from_other_event_types() -> None:
    adapter = TypeAdapter(ChatStreamEvent)
    values = {
        "event": "done",
        "request_id": "stream-001",
        "sequence": 1,
        "delta": "not valid on done",
        "provider_name": "mock",
        "model_name": "mock-model",
        "finish_reason": "stop",
        "created_at": datetime(2026, 8, 27, 4, 0, tzinfo=UTC),
    }

    with pytest.raises(ValidationError):
        adapter.validate_python(values)
