"""Offline contract tests for the vendor-neutral LLM provider boundary."""

import inspect
import json
from collections.abc import AsyncIterator, Callable

import httpx
import pytest
from pydantic import ValidationError

from app.llm import (
    FinishReason,
    LLMException,
    LLMMessage,
    LLMProvider,
    LLMRequest,
    LLMResponse,
    LLMStreamChunk,
    MessageRole,
    ProviderAuthenticationError,
    ProviderConfigurationError,
    ProviderInvalidResponse,
    ProviderNotRegistered,
    ProviderRateLimitError,
    ProviderTimeout,
    ProviderUnavailable,
    TokenUsage,
)
from app.llm.config import LLMSettings
from app.llm.http.client import LLMHTTPClient
from app.llm.providers import (
    DeepSeekProvider,
    MockErrorMode,
    MockProvider,
    OpenAIProvider,
)


type ProviderBuilder = Callable[[], LLMProvider]


def _build_mock_provider() -> LLMProvider:
    return MockProvider(
        response_text="Contract response",
        default_model="contract-default-model",
    )


def _real_provider_settings(provider_name: str) -> LLMSettings:
    return LLMSettings(
        _env_file=None,
        provider=provider_name,
        default_model="contract-fallback-model",
        timeout_seconds=30,
        default_temperature=0.5,
        default_max_tokens=128,
        **{
            f"{provider_name}_api_key": f"{provider_name}-contract-secret",
            f"{provider_name}_base_url": (
                f"https://{provider_name}-contract.example.test/v1"
            ),
            f"{provider_name}_default_model": "contract-default-model",
        },
    )


def _complete_contract_payload(
    model_name: str,
    request_id: str,
) -> dict[str, object]:
    return {
        "id": request_id,
        "model": model_name,
        "choices": [
            {
                "message": {
                    "role": "assistant",
                    "content": "Contract response",
                },
                "finish_reason": "stop",
            }
        ],
        "usage": {
            "prompt_tokens": 3,
            "completion_tokens": 2,
            "total_tokens": 5,
        },
    }


def _stream_contract_payload(model_name: str, request_id: str) -> bytes:
    events = (
        {
            "id": request_id,
            "model": model_name,
            "choices": [
                {
                    "delta": {"content": "Contract response"},
                    "finish_reason": None,
                }
            ],
        },
        {
            "id": request_id,
            "model": model_name,
            "choices": [
                {
                    "delta": {},
                    "finish_reason": "stop",
                }
            ],
        },
        {
            "id": request_id,
            "model": model_name,
            "choices": [],
            "usage": {
                "prompt_tokens": 3,
                "completion_tokens": 2,
                "total_tokens": 5,
            },
        },
    )
    frames = [
        f"data: {json.dumps(event, separators=(',', ':'))}\n\n".encode()
        for event in events
    ]
    frames.append(b"data: [DONE]\n\n")
    return b"".join(frames)


def _build_deepseek_provider() -> LLMProvider:
    settings = _real_provider_settings("deepseek")

    async def handler(request: httpx.Request) -> httpx.Response:
        outgoing = json.loads(request.content)
        if outgoing["stream"]:
            return httpx.Response(
                200,
                content=_stream_contract_payload(
                    outgoing["model"],
                    "deepseek-contract-request",
                ),
            )
        return httpx.Response(
            200,
            json=_complete_contract_payload(
                outgoing["model"],
                "deepseek-contract-request",
            ),
        )

    return DeepSeekProvider(
        settings,
        http_client=LLMHTTPClient(
            settings,
            transport=httpx.MockTransport(handler),
        ),
    )


def _build_openai_provider() -> LLMProvider:
    settings = _real_provider_settings("openai")

    async def handler(request: httpx.Request) -> httpx.Response:
        outgoing = json.loads(request.content)
        if outgoing["stream"]:
            return httpx.Response(
                200,
                content=_stream_contract_payload(
                    outgoing["model"],
                    "openai-contract-request",
                ),
            )
        return httpx.Response(
            200,
            json=_complete_contract_payload(
                outgoing["model"],
                "openai-contract-request",
            ),
        )

    return OpenAIProvider(
        settings,
        http_client=LLMHTTPClient(
            settings,
            transport=httpx.MockTransport(handler),
        ),
    )


PROVIDER_BUILDERS = (
    pytest.param(_build_mock_provider, id="mock"),
    pytest.param(_build_deepseek_provider, id="deepseek"),
    pytest.param(_build_openai_provider, id="openai"),
)


def _messages() -> tuple[LLMMessage, ...]:
    return (
        LLMMessage(role=MessageRole.SYSTEM, content="System input"),
        LLMMessage(role=MessageRole.USER, content="User input"),
    )


def test_provider_interface_exposes_the_stable_minimum_surface() -> None:
    assert isinstance(LLMProvider.__dict__["provider_name"], property)
    assert isinstance(LLMProvider.__dict__["default_model"], property)
    assert callable(LLMProvider.__dict__["generate"])
    assert callable(LLMProvider.__dict__["stream_generate"])
    assert callable(LLMProvider.__dict__["aclose"])


@pytest.mark.asyncio
@pytest.mark.parametrize("provider_builder", PROVIDER_BUILDERS)
async def test_provider_metadata_and_lifecycle_contract(
    provider_builder: ProviderBuilder,
) -> None:
    provider = provider_builder()

    try:
        assert provider.provider_name in {"mock", "deepseek", "openai"}
        assert provider.default_model == "contract-default-model"
        assert inspect.iscoroutinefunction(provider.generate)
        assert callable(provider.stream_generate)
        assert inspect.iscoroutinefunction(provider.aclose)
    finally:
        await provider.aclose()
        await provider.aclose()


@pytest.mark.asyncio
@pytest.mark.parametrize("provider_builder", PROVIDER_BUILDERS)
async def test_provider_complete_generation_contract(
    provider_builder: ProviderBuilder,
) -> None:
    provider: LLMProvider = provider_builder()
    request = LLMRequest(
        messages=_messages(),
        model_name="contract-request-model",
        temperature=0.5,
        max_tokens=128,
        correlation_id="contract-generate",
    )

    try:
        response = await provider.generate(request)
    finally:
        await provider.aclose()
        await provider.aclose()

    assert isinstance(response, LLMResponse)
    assert response.text == "Contract response"
    assert response.provider_name == provider.provider_name
    assert response.model_name == "contract-request-model"
    assert isinstance(response.finish_reason, FinishReason)
    assert response.usage is None or isinstance(response.usage, TokenUsage)
    assert response.provider_request_id is not None
    assert not isinstance(response, (httpx.Request, httpx.Response))
    assert not hasattr(response, "raw_response")
    assert not hasattr(response, "raw_json")
    assert not hasattr(response, "sdk_response")


@pytest.mark.asyncio
@pytest.mark.parametrize("provider_builder", PROVIDER_BUILDERS)
async def test_provider_streaming_generation_contract(
    provider_builder: ProviderBuilder,
) -> None:
    provider: LLMProvider = provider_builder()
    request = LLMRequest(
        messages=_messages(),
        correlation_id="contract-stream",
    )

    try:
        stream = provider.stream_generate(request)
        assert isinstance(stream, AsyncIterator)
        chunks = [chunk async for chunk in stream]
    finally:
        await provider.aclose()
        await provider.aclose()

    assert chunks
    assert all(isinstance(chunk, LLMStreamChunk) for chunk in chunks)
    assert [chunk.sequence for chunk in chunks] == list(range(len(chunks)))
    assert "".join(chunk.delta for chunk in chunks) == "Contract response"
    assert all(chunk.provider_name == provider.provider_name for chunk in chunks)
    assert all(chunk.model_name == provider.default_model for chunk in chunks)
    assert all(not chunk.is_final for chunk in chunks[:-1])
    assert chunks[-1].is_final is True
    assert chunks[-1].finish_reason is FinishReason.STOP
    assert chunks[-1].usage is None or isinstance(chunks[-1].usage, TokenUsage)
    assert len({chunk.provider_request_id for chunk in chunks}) == 1
    assert all(not isinstance(chunk, (httpx.Request, httpx.Response)) for chunk in chunks)
    assert all(not hasattr(chunk, "raw_json") for chunk in chunks)
    assert all(not hasattr(chunk, "sdk_chunk") for chunk in chunks)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("error_mode", "exception_type"),
    (
        (MockErrorMode.TIMEOUT, ProviderTimeout),
        (MockErrorMode.AUTHENTICATION, ProviderAuthenticationError),
        (MockErrorMode.RATE_LIMIT, ProviderRateLimitError),
        (MockErrorMode.UNAVAILABLE, ProviderUnavailable),
    ),
)
async def test_provider_failures_use_the_unified_exception_contract(
    error_mode: MockErrorMode,
    exception_type: type[LLMException],
) -> None:
    provider: LLMProvider = MockProvider(error_mode=error_mode)

    try:
        with pytest.raises(LLMException) as raised:
            await provider.generate(LLMRequest(messages=_messages()))
    finally:
        await provider.aclose()

    assert type(raised.value) is exception_type
    assert raised.value.provider_name == provider.provider_name


@pytest.mark.parametrize(
    ("field_name", "invalid_value"),
    (
        ("temperature", -0.01),
        ("temperature", 2.01),
        ("temperature", float("inf")),
        ("max_tokens", 0),
        ("max_tokens", -1),
        ("max_tokens", 1.5),
    ),
)
def test_request_rejects_invalid_generation_parameters(
    field_name: str,
    invalid_value: object,
) -> None:
    request_values: dict[str, object] = {
        "messages": _messages(),
        field_name: invalid_value,
    }

    with pytest.raises(ValidationError):
        LLMRequest.model_validate(request_values)


def test_request_accepts_generation_parameter_boundaries() -> None:
    minimum = LLMRequest(messages=_messages(), temperature=0, max_tokens=1)
    maximum = LLMRequest(messages=_messages(), temperature=2, max_tokens=1)

    assert minimum.temperature == 0
    assert maximum.temperature == 2


@pytest.mark.parametrize("content", ("", " ", "\t\r\n"))
def test_message_rejects_blank_content(content: str) -> None:
    with pytest.raises(ValidationError):
        LLMMessage(role=MessageRole.USER, content=content)


def test_request_rejects_an_empty_message_list() -> None:
    with pytest.raises(ValidationError):
        LLMRequest(messages=())


@pytest.mark.parametrize("field_name", ("vendor_options", "extra_kwargs"))
def test_request_rejects_vendor_specific_escape_hatches(field_name: str) -> None:
    with pytest.raises(ValidationError):
        LLMRequest.model_validate(
            {
                "messages": _messages(),
                field_name: {"vendor_specific": True},
            }
        )


def test_response_rejects_raw_sdk_objects() -> None:
    response_values = {
        "text": "Contract response",
        "provider_name": "contract",
        "model_name": "contract-model",
        "finish_reason": FinishReason.STOP,
        "raw_sdk_response": object(),
    }

    with pytest.raises(ValidationError):
        LLMResponse.model_validate(response_values)


def test_response_serialization_contains_only_public_contract_fields() -> None:
    response = LLMResponse(
        text="Contract response",
        provider_name="contract",
        model_name="contract-model",
        finish_reason=FinishReason.STOP,
        provider_request_id="contract-request",
    )

    assert set(response.model_dump()) == {
        "text",
        "provider_name",
        "model_name",
        "finish_reason",
        "usage",
        "provider_request_id",
    }


def test_stream_completion_metadata_is_restricted_to_final_chunks() -> None:
    common_values = {
        "sequence": 0,
        "provider_name": "contract",
        "model_name": "contract-model",
    }

    with pytest.raises(ValidationError):
        LLMStreamChunk.model_validate(
            {**common_values, "finish_reason": FinishReason.STOP}
        )
    with pytest.raises(ValidationError):
        LLMStreamChunk.model_validate({**common_values, "is_final": True})


EXCEPTION_TYPES: tuple[type[LLMException], ...] = (
    ProviderTimeout,
    ProviderAuthenticationError,
    ProviderRateLimitError,
    ProviderUnavailable,
    ProviderConfigurationError,
    ProviderNotRegistered,
    ProviderInvalidResponse,
)


@pytest.mark.parametrize("exception_type", EXCEPTION_TYPES)
def test_exception_hierarchy_is_stable_and_vendor_neutral(
    exception_type: type[LLMException],
) -> None:
    error = exception_type(
        "Safe provider failure",
        provider_name="contract",
        provider_request_id="contract-request",
    )

    try:
        raise error
    except LLMException as caught:
        assert caught is error

    assert all(not base.__module__.startswith("fastapi") for base in type(error).__mro__)
    assert all("openai" not in base.__module__ for base in type(error).__mro__)
    assert all("deepseek" not in base.__module__ for base in type(error).__mro__)
    assert not hasattr(error, "raw_response")
    assert not hasattr(error, "sdk_response")
    assert "api-key" not in repr(error).lower()
    assert set(vars(error)) <= {
        "message",
        "provider_name",
        "provider_request_id",
        "retry_after_seconds",
    }


def test_public_exception_codes_are_unique() -> None:
    codes = [exception_type.code for exception_type in EXCEPTION_TYPES]

    assert len(codes) == len(set(codes))
