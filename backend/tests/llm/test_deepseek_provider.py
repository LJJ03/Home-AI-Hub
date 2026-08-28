"""Offline request, response, lifecycle, and architecture tests for DeepSeek."""

from __future__ import annotations

import ast
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
    LLMMessage,
    LLMRequest,
    LLMResponse,
    MessageRole,
    ProviderInvalidResponse,
)
from app.llm.config import LLMSettings
from app.llm.http.client import LLMHTTPClient
from app.llm.providers.deepseek import DeepSeekProvider


BACKEND_ROOT = Path(__file__).resolve().parents[2]
PROVIDER_MODULE_PATH = BACKEND_ROOT / "app/llm/providers/deepseek.py"


def _settings(**overrides: Any) -> LLMSettings:
    values: dict[str, Any] = {
        "provider": "deepseek",
        "default_model": "generic-fallback-model",
        "timeout_seconds": 30.0,
        "default_temperature": 0.25,
        "default_max_tokens": 768,
        "deepseek_api_key": "deepseek-offline-test-secret",
        "deepseek_base_url": "https://deepseek.example.test/api/v1",
        "deepseek_default_model": "configured-deepseek-model",
        "_env_file": None,
    }
    values.update(overrides)
    return LLMSettings(**values)


def _request(**overrides: Any) -> LLMRequest:
    values: dict[str, Any] = {
        "messages": (
            LLMMessage(role=MessageRole.SYSTEM, content="System instruction"),
            LLMMessage(role=MessageRole.USER, content="Offline user prompt"),
        ),
        "correlation_id": "deepseek-offline-correlation",
    }
    values.update(overrides)
    return LLMRequest(**values)


def _success_payload(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "id": "deepseek-provider-request-id",
        "model": "deepseek-response-model",
        "choices": [
            {
                "index": 0,
                "message": {
                    "role": "assistant",
                    "content": "Normalized answer",
                    "reasoning_content": "Internal reasoning must stay private",
                },
                "finish_reason": "stop",
            }
        ],
        "usage": {
            "prompt_tokens": 11,
            "completion_tokens": 7,
            "total_tokens": 18,
        },
    }
    payload.update(overrides)
    return payload


def _provider(
    handler: Any,
    *,
    settings: LLMSettings | None = None,
) -> DeepSeekProvider:
    configured_settings = settings or _settings()
    http_client = LLMHTTPClient(
        configured_settings,
        transport=httpx.MockTransport(handler),
    )
    return DeepSeekProvider(configured_settings, http_client=http_client)


@pytest.mark.asyncio
async def test_request_is_mapped_to_chat_completions_without_extra_features() -> None:
    captured: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(200, json=_success_payload())

    provider = _provider(handler)
    assert "deepseek-offline-test-secret" not in repr(provider)
    assert "deepseek-offline-test-secret" not in str(provider)
    request = _request(
        model_name="request-selected-model",
        temperature=0.65,
        max_tokens=321,
    )
    try:
        await provider.generate(request)
    finally:
        await provider.aclose()

    outgoing = captured[0]
    payload = json.loads(outgoing.content)
    assert outgoing.method == "POST"
    assert str(outgoing.url) == (
        "https://deepseek.example.test/api/v1/chat/completions"
    )
    actual_header_digest = hashlib.sha256(
        outgoing.headers["Authorization"].encode("utf-8")
    ).digest()
    expected_header_digest = hashlib.sha256(
        b"Bearer deepseek-offline-test-secret"
    ).digest()
    assert hmac.compare_digest(
        actual_header_digest,
        expected_header_digest,
    )
    assert outgoing.headers["Content-Type"].startswith("application/json")
    assert payload == {
        "messages": [
            {"role": "system", "content": "System instruction"},
            {"role": "user", "content": "Offline user prompt"},
        ],
        "model": "request-selected-model",
        "temperature": 0.65,
        "max_tokens": 321,
        "stream": False,
    }
    assert set(payload) == {
        "messages",
        "model",
        "temperature",
        "max_tokens",
        "stream",
    }


@pytest.mark.asyncio
async def test_generation_defaults_come_from_configuration() -> None:
    captured_payloads: list[dict[str, Any]] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        captured_payloads.append(json.loads(request.content))
        return httpx.Response(200, json=_success_payload())

    provider = _provider(handler)
    try:
        await provider.generate(_request())
    finally:
        await provider.aclose()

    assert captured_payloads[0]["model"] == "configured-deepseek-model"
    assert captured_payloads[0]["temperature"] == 0.25
    assert captured_payloads[0]["max_tokens"] == 768


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
    assert response.text == "Normalized answer"
    assert response.provider_name == "deepseek"
    assert response.model_name == "deepseek-response-model"
    assert response.finish_reason is FinishReason.STOP
    assert response.provider_request_id == "deepseek-provider-request-id"
    assert response.usage is not None
    assert response.usage.input_tokens == 11
    assert response.usage.output_tokens == 7
    assert response.usage.total_tokens == 18
    assert "Internal reasoning" not in response.text
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
        ("new_future_reason", FinishReason.UNKNOWN),
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
        with pytest.raises(ProviderInvalidResponse):
            await provider.generate(_request())
    finally:
        await provider.aclose()


@pytest.mark.asyncio
async def test_aclose_is_idempotent_after_a_normal_request() -> None:
    class RecordingTransport(httpx.MockTransport):
        def __init__(self) -> None:
            super().__init__(
                lambda _: httpx.Response(200, json=_success_payload())
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

    await provider.generate(_request())
    await provider.aclose()
    await provider.aclose()

    assert transport.close_calls == 1


def test_module_has_no_import_time_http_client_construction() -> None:
    tree = ast.parse(PROVIDER_MODULE_PATH.read_text(encoding="utf-8"))
    top_level_calls = [
        node
        for statement in tree.body
        for node in ast.walk(statement)
        if not isinstance(statement, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef))
        and isinstance(node, ast.Call)
    ]

    assert not any(
        isinstance(call.func, ast.Name) and call.func.id == "LLMHTTPClient"
        for call in top_level_calls
    )


def test_deepseek_adapter_respects_frozen_architecture_boundaries() -> None:
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
        "openai",
        "deepseek",
    )

    assert not any(
        imported == prefix or imported.startswith(f"{prefix}.")
        for imported in imports
        for prefix in forbidden_prefixes
    )
    assert "api.deepseek.com" not in source
    assert "deepseek-chat" not in source
    assert "logging" not in imports

    chat_router = (BACKEND_ROOT / "app/api/v1/routes/chat.py").read_text("utf-8")
    chat_service = (BACKEND_ROOT / "app/services/chat.py").read_text("utf-8")
    factory = (BACKEND_ROOT / "app/llm/factory.py").read_text("utf-8")
    bootstrap = (BACKEND_ROOT / "app/llm/bootstrap.py").read_text("utf-8")
    provider_exports = (
        BACKEND_ROOT / "app/llm/providers/__init__.py"
    ).read_text("utf-8")

    assert "DeepSeekProvider" not in chat_router
    assert "DeepSeekProvider" not in chat_service
    assert "deepseek" not in factory.lower()
    assert "DeepSeekProvider" in bootstrap
    assert '"deepseek"' in bootstrap
    assert "DeepSeekProvider" in provider_exports

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
