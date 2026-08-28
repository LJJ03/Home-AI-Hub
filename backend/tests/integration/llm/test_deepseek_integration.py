"""Explicitly opted-in, minimal real DeepSeek provider checks."""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Mapping

import pytest

from app.llm import FinishReason, LLMMessage, LLMRequest, MessageRole
from app.llm.config import LLMSettings
from app.llm.providers.deepseek import DeepSeekProvider
from app.schemas.chat import ChatResponse


type ProviderEnvironmentLoader = Callable[
    [str, tuple[str, ...]],
    Mapping[str, str],
]

_REQUIRED_ENVIRONMENT = (
    "DEEPSEEK_API_KEY",
    "DEEPSEEK_BASE_URL",
    "DEEPSEEK_DEFAULT_MODEL",
)
_OPERATION_TIMEOUT_SECONDS = 45.0


def _settings(environment: Mapping[str, str]) -> LLMSettings:
    return LLMSettings(
        _env_file=None,
        provider="deepseek",
        default_model=environment["DEEPSEEK_DEFAULT_MODEL"],
        timeout_seconds=30.0,
        connect_timeout_seconds=10.0,
        read_timeout_seconds=30.0,
        stream_timeout_seconds=30.0,
        default_temperature=0.0,
        default_max_tokens=16,
        deepseek_api_key=environment["DEEPSEEK_API_KEY"],
        deepseek_base_url=environment["DEEPSEEK_BASE_URL"],
        deepseek_default_model=environment["DEEPSEEK_DEFAULT_MODEL"],
    )


def _request() -> LLMRequest:
    return LLMRequest(
        messages=(LLMMessage(role=MessageRole.USER, content="Say hi."),),
        temperature=0.0,
        max_tokens=16,
        correlation_id="deepseek-integration-minimal",
    )


def _assert_public_chat_contract_hides_provider_request_id() -> None:
    assert "provider_request_id" not in ChatResponse.model_fields


@pytest.mark.llm_integration
@pytest.mark.asyncio
async def test_deepseek_minimal_non_streaming_call(
    require_llm_provider_environment: ProviderEnvironmentLoader,
) -> None:
    environment = require_llm_provider_environment(
        "DeepSeek",
        _REQUIRED_ENVIRONMENT,
    )
    provider = DeepSeekProvider(_settings(environment))

    try:
        async with asyncio.timeout(_OPERATION_TIMEOUT_SECONDS):
            response = await provider.generate(_request())
    finally:
        await provider.aclose()

    assert response.provider_name == "deepseek"
    assert response.model_name.strip()
    assert isinstance(response.finish_reason, FinishReason)
    assert response.text == "" or response.text.strip()
    if response.provider_request_id is not None:
        _assert_public_chat_contract_hides_provider_request_id()


@pytest.mark.llm_integration
@pytest.mark.asyncio
async def test_deepseek_minimal_streaming_call(
    require_llm_provider_environment: ProviderEnvironmentLoader,
) -> None:
    environment = require_llm_provider_environment(
        "DeepSeek",
        _REQUIRED_ENVIRONMENT,
    )
    provider = DeepSeekProvider(_settings(environment))
    iterator = provider.stream_generate(_request())
    deltas: list[str] = []
    final_received = False
    provider_request_id_seen = False

    try:
        async with asyncio.timeout(_OPERATION_TIMEOUT_SECONDS):
            try:
                async for chunk in iterator:
                    assert chunk.provider_name == "deepseek"
                    assert chunk.model_name.strip()
                    if chunk.delta:
                        deltas.append(chunk.delta)
                    if chunk.provider_request_id is not None:
                        provider_request_id_seen = True
                    if chunk.is_final:
                        assert isinstance(chunk.finish_reason, FinishReason)
                        final_received = True
            finally:
                await iterator.aclose()
    finally:
        await provider.aclose()

    reconstructed_text = "".join(deltas)
    assert reconstructed_text == "" or reconstructed_text.strip()
    assert final_received is True
    if provider_request_id_seen:
        _assert_public_chat_contract_hides_provider_request_id()

