"""Offline contract tests for the OpenAI non-streaming HTTP adapter."""

from __future__ import annotations

import ast
import asyncio
import hashlib
import hmac
import json
import tomllib
from pathlib import Path
from typing import Any

import httpx
import pytest

from app.llm import (
    FinishReason,
    LLMException,
    LLMMessage,
    LLMRequest,
    LLMResponse,
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
from app.llm.providers.openai import OpenAIProvider


BACKEND_ROOT = Path(__file__).resolve().parents[2]
PROVIDER_MODULE_PATH = BACKEND_ROOT / "app/llm/providers/openai.py"
SENSITIVE_API_KEY = "openai-offline-test-secret-never-render"
SENSITIVE_PROMPT = "complete OpenAI prompt must never leak"
SENSITIVE_RESPONSE = "complete OpenAI response must never leak"


def _settings(**overrides: Any) -> LLMSettings:
    values: dict[str, Any] = {
        "provider": "openai",
        "default_model": "generic-fallback-model",
        "timeout_seconds": 30.0,
        "default_temperature": 0.35,
        "default_max_tokens": 704,
        "openai_api_key": SENSITIVE_API_KEY,
        "openai_base_url": "https://openai-offline.example.test/v1",
        "openai_default_model": "configured-openai-model",
        "_env_file": None,
    }
    values.update(overrides)
    return LLMSettings(**values)


def _request(**overrides: Any) -> LLMRequest:
    values: dict[str, Any] = {
        "messages": (
            LLMMessage(role=MessageRole.SYSTEM, content="System instruction"),
            LLMMessage(role=MessageRole.USER, content=SENSITIVE_PROMPT),
        ),
        "correlation_id": "openai-offline-correlation",
    }
    values.update(overrides)
    return LLMRequest(**values)


def _success_payload(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "id": "openai-provider-request-id",
        "model": "openai-response-model",
        "choices": [
            {
                "index": 0,
                "message": {
                    "role": "assistant",
                    "content": "Normalized OpenAI answer",
                },
                "finish_reason": "stop",
            }
        ],
        "usage": {
            "prompt_tokens": 17,
            "completion_tokens": 9,
            "total_tokens": 26,
        },
    }
    payload.update(overrides)
    return payload


def _provider(
    handler: Any,
    *,
    settings: LLMSettings | None = None,
) -> OpenAIProvider:
    configured_settings = settings or _settings()
    client = LLMHTTPClient(
        configured_settings,
        transport=httpx.MockTransport(handler),
    )
    return OpenAIProvider(configured_settings, http_client=client)


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
async def test_request_maps_only_supported_chat_completion_fields() -> None:
    captured: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(200, json=_success_payload())

    provider = _provider(handler)
    request = _request(
        model_name="request-selected-openai-model",
        temperature=0.8,
        max_tokens=333,
    )
    assert SENSITIVE_API_KEY not in repr(provider)
    assert SENSITIVE_API_KEY not in str(provider)
    try:
        await provider.generate(request)
    finally:
        await provider.aclose()

    outgoing = captured[0]
    payload = json.loads(outgoing.content)
    assert outgoing.method == "POST"
    assert str(outgoing.url) == (
        "https://openai-offline.example.test/v1/chat/completions"
    )
    actual_digest = hashlib.sha256(
        outgoing.headers["Authorization"].encode()
    ).digest()
    expected_digest = hashlib.sha256(
        f"Bearer {SENSITIVE_API_KEY}".encode()
    ).digest()
    assert hmac.compare_digest(actual_digest, expected_digest)
    assert outgoing.headers["Content-Type"].startswith("application/json")
    assert payload == {
        "messages": [
            {"role": "system", "content": "System instruction"},
            {"role": "user", "content": SENSITIVE_PROMPT},
        ],
        "model": "request-selected-openai-model",
        "temperature": 0.8,
        "max_completion_tokens": 333,
        "stream": False,
        "n": 1,
        "store": False,
    }
    assert "max_tokens" not in payload
    assert set(payload) == {
        "messages",
        "model",
        "temperature",
        "max_completion_tokens",
        "stream",
        "n",
        "store",
    }


@pytest.mark.asyncio
async def test_request_defaults_come_from_configuration() -> None:
    captured_payloads: list[dict[str, Any]] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        captured_payloads.append(json.loads(request.content))
        return httpx.Response(200, json=_success_payload())

    provider = _provider(handler)
    try:
        await provider.generate(_request())
    finally:
        await provider.aclose()

    assert captured_payloads[0]["model"] == "configured-openai-model"
    assert captured_payloads[0]["temperature"] == 0.35
    assert captured_payloads[0]["max_completion_tokens"] == 704


@pytest.mark.asyncio
async def test_success_response_maps_to_frozen_llm_response() -> None:
    provider = _provider(
        lambda _: httpx.Response(200, json=_success_payload())
    )
    try:
        response = await provider.generate(_request())
    finally:
        await provider.aclose()

    assert isinstance(response, LLMResponse)
    assert response.text == "Normalized OpenAI answer"
    assert response.provider_name == "openai"
    assert response.model_name == "openai-response-model"
    assert response.finish_reason is FinishReason.STOP
    assert response.provider_request_id == "openai-provider-request-id"
    assert response.usage is not None
    assert response.usage.input_tokens == 17
    assert response.usage.output_tokens == 9
    assert response.usage.total_tokens == 26
    assert not hasattr(response, "raw_response")
    assert not hasattr(response, "httpx_response")


@pytest.mark.asyncio
async def test_missing_usage_maps_to_none() -> None:
    payload = _success_payload()
    payload.pop("usage")
    provider = _provider(lambda _: httpx.Response(200, json=payload))
    try:
        response = await provider.generate(_request())
    finally:
        await provider.aclose()

    assert response.usage is None


@pytest.mark.asyncio
async def test_missing_response_model_falls_back_to_requested_model() -> None:
    payload = _success_payload()
    payload.pop("model")
    provider = _provider(lambda _: httpx.Response(200, json=payload))
    try:
        response = await provider.generate(
            _request(model_name="request-fallback-model")
        )
    finally:
        await provider.aclose()

    assert response.model_name == "request-fallback-model"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("vendor_reason", "expected_reason"),
    [
        ("stop", FinishReason.STOP),
        ("length", FinishReason.LENGTH),
        ("content_filter", FinishReason.CONTENT_FILTER),
        ("future_reason", FinishReason.UNKNOWN),
    ],
)
async def test_finish_reason_is_normalized(
    vendor_reason: str,
    expected_reason: FinishReason,
) -> None:
    payload = _success_payload()
    payload["choices"][0]["finish_reason"] = vendor_reason
    provider = _provider(lambda _: httpx.Response(200, json=payload))
    try:
        response = await provider.generate(_request())
    finally:
        await provider.aclose()

    assert response.finish_reason is expected_reason


@pytest.mark.asyncio
@pytest.mark.parametrize("unsupported_field", ["tool_calls", "function_call"])
async def test_tool_and_function_results_are_rejected(
    unsupported_field: str,
) -> None:
    payload = _success_payload()
    payload["choices"][0]["message"][unsupported_field] = {"unsafe": True}
    provider = _provider(lambda _: httpx.Response(200, json=payload))
    try:
        with pytest.raises(ProviderInvalidResponse) as exc_info:
            await provider.generate(_request())
    finally:
        await provider.aclose()

    _assert_safe_normalized_error(exc_info.value)


@pytest.mark.asyncio
@pytest.mark.parametrize("finish_reason", ["tool_calls", "function_call"])
async def test_tool_and_function_finish_reasons_are_rejected(
    finish_reason: str,
) -> None:
    payload = _success_payload()
    payload["choices"][0]["finish_reason"] = finish_reason
    provider = _provider(lambda _: httpx.Response(200, json=payload))
    try:
        with pytest.raises(ProviderInvalidResponse):
            await provider.generate(_request())
    finally:
        await provider.aclose()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("status_code", "exception_type"),
    [
        (400, ProviderConfigurationError),
        (404, ProviderConfigurationError),
        (422, ProviderConfigurationError),
        (401, ProviderAuthenticationError),
        (403, ProviderAuthenticationError),
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
    assert exc_info.value.provider_name == "openai"
    _assert_safe_normalized_error(exc_info.value)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("header_value", "expected_retry_after"),
    [
        ("10.5", 10.5),
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
async def test_non_json_response_maps_to_invalid_response() -> None:
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
async def test_invalid_json_shape_maps_to_invalid_response(
    invalid_payload: Any,
) -> None:
    provider = _provider(lambda _: httpx.Response(200, json=invalid_payload))
    try:
        with pytest.raises(ProviderInvalidResponse) as exc_info:
            await provider.generate(_request())
    finally:
        await provider.aclose()

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
    ["openai_api_key", "openai_base_url", "openai_default_model"],
)
def test_provider_fails_fast_when_configuration_is_missing(
    missing_field: str,
) -> None:
    values: dict[str, Any] = {
        "provider": "mock",
        "default_model": "generic-model",
        "timeout_seconds": 30.0,
        "default_temperature": 0.2,
        "default_max_tokens": 512,
        "openai_api_key": SENSITIVE_API_KEY,
        "openai_base_url": "https://openai-missing.example.test/v1",
        "openai_default_model": "openai-configured-model",
        "_env_file": None,
    }
    values[missing_field] = None
    settings = LLMSettings(**values)

    with pytest.raises(ProviderConfigurationError) as exc_info:
        OpenAIProvider(settings)

    _assert_safe_normalized_error(exc_info.value)


@pytest.mark.asyncio
@pytest.mark.parametrize("status_code", [200, 503])
async def test_resources_close_idempotently_after_request(
    status_code: int,
) -> None:
    class RecordingTransport(httpx.MockTransport):
        def __init__(self) -> None:
            super().__init__(
                lambda _: httpx.Response(
                    status_code,
                    json=(
                        _success_payload()
                        if status_code == 200
                        else None
                    ),
                    text=(SENSITIVE_RESPONSE if status_code != 200 else None),
                )
            )
            self.close_calls = 0

        async def aclose(self) -> None:
            self.close_calls += 1
            await super().aclose()

    settings = _settings()
    transport = RecordingTransport()
    provider = OpenAIProvider(
        settings,
        http_client=LLMHTTPClient(settings, transport=transport),
    )

    try:
        if status_code == 200:
            await provider.generate(_request())
        else:
            with pytest.raises(ProviderUnavailable):
                await provider.generate(_request())
    finally:
        await provider.aclose()
        await provider.aclose()

    assert transport.close_calls == 1


def test_module_has_no_import_time_http_client_construction() -> None:
    tree = ast.parse(PROVIDER_MODULE_PATH.read_text(encoding="utf-8"))
    top_level_calls = [
        node
        for statement in tree.body
        for node in ast.walk(statement)
        if not isinstance(
            statement,
            (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef),
        )
        and isinstance(node, ast.Call)
    ]

    assert not any(
        isinstance(call.func, ast.Name) and call.func.id == "LLMHTTPClient"
        for call in top_level_calls
    )


def test_openai_adapter_respects_frozen_architecture_boundaries() -> None:
    source = PROVIDER_MODULE_PATH.read_text(encoding="utf-8")
    tree = ast.parse(source)
    imports = {
        node.module or ""
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom)
    }
    imports.update(
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    )
    forbidden_prefixes = (
        "fastapi",
        "sqlalchemy",
        "redis",
        "app.api",
        "app.db",
        "app.models",
        "app.repositories",
        "app.services",
        "app.llm.providers.deepseek",
        "openai",
        "deepseek",
    )

    assert not any(
        imported == prefix or imported.startswith(f"{prefix}.")
        for imported in imports
        for prefix in forbidden_prefixes
    )
    assert "api.openai.com" not in source
    assert '"gpt-' not in source
    assert "logging" not in imports

    chat_router = (BACKEND_ROOT / "app/api/v1/routes/chat.py").read_text("utf-8")
    chat_service = (BACKEND_ROOT / "app/services/chat.py").read_text("utf-8")
    factory = (BACKEND_ROOT / "app/llm/factory.py").read_text("utf-8")
    bootstrap = (BACKEND_ROOT / "app/llm/bootstrap.py").read_text("utf-8")
    provider_exports = (
        BACKEND_ROOT / "app/llm/providers/__init__.py"
    ).read_text("utf-8")

    assert "OpenAIProvider" not in chat_router
    assert "OpenAIProvider" not in chat_service
    assert "openai" not in factory.lower()
    assert "OpenAIProvider" in bootstrap
    assert '"openai"' in bootstrap
    assert "OpenAIProvider" in provider_exports

    project = tomllib.loads(
        (BACKEND_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    )
    dependencies = list(project["project"]["dependencies"])
    for group in project["project"].get("optional-dependencies", {}).values():
        dependencies.extend(group)
    assert not any(
        dependency.lower().startswith(("openai", "deepseek"))
        for dependency in dependencies
    )
