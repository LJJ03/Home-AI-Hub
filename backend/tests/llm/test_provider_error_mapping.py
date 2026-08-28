"""Offline DeepSeek HTTP, transport, and response error mapping tests."""

from __future__ import annotations

import asyncio
from typing import Any

import httpx
import pytest

from app.llm import (
    LLMException,
    LLMMessage,
    LLMRequest,
    MessageRole,
    ProviderAuthenticationError,
    ProviderConfigurationError,
    ProviderInvalidResponse,
    ProviderRateLimitError,
    ProviderTimeout,
    ProviderUnavailable,
)
from app.llm.config import LLMSettings
from app.llm.http.client import LLMHTTPClient
from app.llm.providers.deepseek import DeepSeekProvider


SENSITIVE_API_KEY = "deepseek-error-test-secret"
SENSITIVE_PROMPT = "complete-sensitive-prompt-must-not-leak"
SENSITIVE_RESPONSE = "complete-sensitive-provider-response-must-not-leak"


def _settings(**overrides: Any) -> LLMSettings:
    values: dict[str, Any] = {
        "provider": "deepseek",
        "default_model": "generic-error-test-model",
        "timeout_seconds": 30.0,
        "default_temperature": 0.25,
        "default_max_tokens": 512,
        "deepseek_api_key": SENSITIVE_API_KEY,
        "deepseek_base_url": "https://deepseek-errors.example.test/v1",
        "deepseek_default_model": "deepseek-error-test-model",
        "_env_file": None,
    }
    values.update(overrides)
    return LLMSettings(**values)


def _request() -> LLMRequest:
    return LLMRequest(
        messages=(
            LLMMessage(role=MessageRole.USER, content=SENSITIVE_PROMPT),
        ),
        correlation_id="deepseek-error-correlation",
    )


def _success_payload() -> dict[str, Any]:
    return {
        "id": "deepseek-error-request-id",
        "model": "deepseek-error-response-model",
        "choices": [
            {
                "message": {
                    "role": "assistant",
                    "content": "Safe answer",
                },
                "finish_reason": "stop",
            }
        ],
    }


def _provider(handler: Any) -> DeepSeekProvider:
    settings = _settings()
    client = LLMHTTPClient(
        settings,
        transport=httpx.MockTransport(handler),
    )
    return DeepSeekProvider(settings, http_client=client)


def _assert_safe_normalized_error(error: LLMException) -> None:
    rendered = f"{error!s}\n{error!r}"
    assert SENSITIVE_API_KEY not in rendered
    assert SENSITIVE_PROMPT not in rendered
    assert SENSITIVE_RESPONSE not in rendered
    assert "Authorization" not in rendered
    assert "httpx" not in rendered.lower()
    assert not isinstance(error, httpx.HTTPError)
    assert error.provider_request_id is None
    assert error.__cause__ is None
    assert error.__context__ is None
    assert not hasattr(error, "request")
    assert not hasattr(error, "response")


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("status_code", "exception_type"),
    [
        (400, ProviderConfigurationError),
        (404, ProviderConfigurationError),
        (422, ProviderConfigurationError),
        (401, ProviderAuthenticationError),
        (403, ProviderAuthenticationError),
        (402, ProviderConfigurationError),
        (408, ProviderTimeout),
        (429, ProviderRateLimitError),
        (500, ProviderUnavailable),
        (503, ProviderUnavailable),
    ],
)
async def test_http_status_maps_to_unified_exception(
    status_code: int,
    exception_type: type[LLMException],
) -> None:
    provider = _provider(
        lambda _: httpx.Response(status_code, text=SENSITIVE_RESPONSE)
    )
    try:
        with pytest.raises(exception_type) as exc_info:
            await provider.generate(_request())
    finally:
        await provider.aclose()

    assert type(exc_info.value) is exception_type
    assert exc_info.value.provider_name == "deepseek"
    _assert_safe_normalized_error(exc_info.value)


@pytest.mark.asyncio
async def test_httpx_timeout_maps_without_original_exception_context() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout(
            f"timeout {SENSITIVE_API_KEY} {SENSITIVE_PROMPT}",
            request=request,
        )

    provider = _provider(handler)
    try:
        with pytest.raises(ProviderTimeout) as exc_info:
            await provider.generate(_request())
    finally:
        await provider.aclose()

    _assert_safe_normalized_error(exc_info.value)


@pytest.mark.asyncio
async def test_httpx_network_error_maps_to_provider_unavailable() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError(
            f"network {SENSITIVE_API_KEY} {SENSITIVE_RESPONSE}",
            request=request,
        )

    provider = _provider(handler)
    try:
        with pytest.raises(ProviderUnavailable) as exc_info:
            await provider.generate(_request())
    finally:
        await provider.aclose()

    _assert_safe_normalized_error(exc_info.value)


@pytest.mark.asyncio
async def test_non_json_response_maps_without_original_decoder_context() -> None:
    provider = _provider(
        lambda _: httpx.Response(200, text=SENSITIVE_RESPONSE)
    )
    try:
        with pytest.raises(ProviderInvalidResponse) as exc_info:
            await provider.generate(_request())
    finally:
        await provider.aclose()

    _assert_safe_normalized_error(exc_info.value)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "invalid_payload",
    [
        None,
        {},
        {"choices": []},
        {"choices": [{}, {}]},
        {"choices": [None]},
        {"choices": [{"message": None, "finish_reason": "stop"}]},
        {
            "choices": [
                {"message": {"content": None}, "finish_reason": "stop"}
            ]
        },
        {
            "choices": [
                {"message": {"content": "answer"}, "finish_reason": None}
            ]
        },
        {
            "choices": [
                {"message": {"content": "answer"}, "finish_reason": "stop"}
            ],
            "usage": {"prompt_tokens": -1},
        },
    ],
)
async def test_invalid_json_shape_maps_to_provider_invalid_response(
    invalid_payload: Any,
) -> None:
    provider = _provider(
        lambda _: httpx.Response(200, json=invalid_payload)
    )
    try:
        with pytest.raises(ProviderInvalidResponse) as exc_info:
            await provider.generate(_request())
    finally:
        await provider.aclose()

    _assert_safe_normalized_error(exc_info.value)


@pytest.mark.asyncio
@pytest.mark.parametrize("finish_reason", ["tool_calls", "function_call"])
async def test_tool_finish_reason_maps_to_invalid_response(
    finish_reason: str,
) -> None:
    payload = _success_payload()
    payload["choices"][0]["finish_reason"] = finish_reason
    provider = _provider(lambda _: httpx.Response(200, json=payload))
    try:
        with pytest.raises(ProviderInvalidResponse) as exc_info:
            await provider.generate(_request())
    finally:
        await provider.aclose()

    _assert_safe_normalized_error(exc_info.value)


@pytest.mark.asyncio
async def test_insufficient_system_resource_maps_to_unavailable() -> None:
    payload = _success_payload()
    payload["choices"][0]["finish_reason"] = "insufficient_system_resource"
    provider = _provider(lambda _: httpx.Response(200, json=payload))
    try:
        with pytest.raises(ProviderUnavailable) as exc_info:
            await provider.generate(_request())
    finally:
        await provider.aclose()

    _assert_safe_normalized_error(exc_info.value)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("header_value", "expected_retry_after"),
    [
        ("12.5", 12.5),
        ("-1", None),
        ("inf", None),
        ("not-a-number", None),
    ],
)
async def test_retry_after_accepts_only_finite_non_negative_seconds(
    header_value: str,
    expected_retry_after: float | None,
) -> None:
    provider = _provider(
        lambda _: httpx.Response(
            429,
            headers={"Retry-After": header_value},
            text=SENSITIVE_RESPONSE,
        )
    )
    try:
        with pytest.raises(ProviderRateLimitError) as exc_info:
            await provider.generate(_request())
    finally:
        await provider.aclose()

    assert exc_info.value.retry_after_seconds == expected_retry_after
    _assert_safe_normalized_error(exc_info.value)


@pytest.mark.asyncio
async def test_cancelled_error_propagates_unchanged() -> None:
    async def handler(_: httpx.Request) -> httpx.Response:
        raise asyncio.CancelledError

    provider = _provider(handler)
    try:
        with pytest.raises(asyncio.CancelledError):
            await provider.generate(_request())
    finally:
        await provider.aclose()


@pytest.mark.parametrize(
    "missing_field",
    ["deepseek_api_key", "deepseek_base_url", "deepseek_default_model"],
)
def test_provider_fails_fast_when_its_configuration_is_missing(
    missing_field: str,
) -> None:
    values: dict[str, Any] = {
        "provider": "mock",
        "default_model": "generic-model",
        "timeout_seconds": 30.0,
        "default_temperature": 0.2,
        "default_max_tokens": 512,
        "deepseek_api_key": SENSITIVE_API_KEY,
        "deepseek_base_url": "https://deepseek-errors.example.test/v1",
        "deepseek_default_model": "deepseek-model",
        "_env_file": None,
    }
    values[missing_field] = None
    settings = LLMSettings(**values)

    with pytest.raises(ProviderConfigurationError) as exc_info:
        DeepSeekProvider(settings)

    _assert_safe_normalized_error(exc_info.value)


@pytest.mark.asyncio
async def test_resources_can_close_after_an_exception() -> None:
    class RecordingTransport(httpx.MockTransport):
        def __init__(self) -> None:
            super().__init__(
                lambda _: httpx.Response(503, text=SENSITIVE_RESPONSE)
            )
            self.close_calls = 0

        async def aclose(self) -> None:
            self.close_calls += 1
            await super().aclose()

    settings = _settings()
    transport = RecordingTransport()
    provider = DeepSeekProvider(
        settings,
        http_client=LLMHTTPClient(settings, transport=transport),
    )
    try:
        with pytest.raises(ProviderUnavailable):
            await provider.generate(_request())
    finally:
        await provider.aclose()

    assert transport.close_calls == 1
