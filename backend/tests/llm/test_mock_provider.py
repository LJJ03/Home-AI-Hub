"""Contract tests for the deterministic offline LLM provider."""

import pytest

from app.llm import (
    FinishReason,
    LLMException,
    LLMMessage,
    LLMProvider,
    LLMRequest,
    MessageRole,
    ProviderAuthenticationError,
    ProviderRateLimitError,
    ProviderTimeout,
    ProviderUnavailable,
)
from app.llm.providers import MockErrorMode, MockProvider


def _request(*, model_name: str | None = None) -> LLMRequest:
    return LLMRequest(
        messages=(
            LLMMessage(role=MessageRole.USER, content="Deterministic input"),
        ),
        model_name=model_name,
        correlation_id="test-correlation-id",
    )


@pytest.mark.asyncio
async def test_generate_returns_deterministic_normalized_response() -> None:
    provider: LLMProvider = MockProvider(
        response_text="Deterministic response",
        default_model="mock-default",
    )
    request = _request()

    first_response = await provider.generate(request)
    second_response = await provider.generate(request)

    assert first_response.text == "Deterministic response"
    assert first_response.provider_name == "mock"
    assert first_response.model_name == "mock-default"
    assert first_response.finish_reason is FinishReason.STOP
    assert first_response.usage is None
    assert first_response.provider_request_id == "mock-request-000001"
    assert second_response.provider_request_id == "mock-request-000002"

    mock_provider = provider
    assert isinstance(mock_provider, MockProvider)
    assert mock_provider.recorded_requests == (request, request)
    await provider.aclose()


@pytest.mark.asyncio
async def test_stream_generate_reassembles_the_configured_response() -> None:
    provider = MockProvider(
        response_text="Deterministic streamed response",
        default_model="mock-default",
    )
    request = _request(model_name="mock-override")

    chunks = [chunk async for chunk in provider.stream_generate(request)]
    content_chunks = chunks[:-1]
    final_chunk = chunks[-1]

    assert "".join(chunk.delta for chunk in content_chunks) == (
        "Deterministic streamed response"
    )
    assert [chunk.sequence for chunk in chunks] == list(range(len(chunks)))
    assert all(chunk.provider_name == "mock" for chunk in chunks)
    assert all(chunk.model_name == "mock-override" for chunk in chunks)
    assert all(
        chunk.provider_request_id == "mock-request-000001" for chunk in chunks
    )
    assert all(not chunk.is_final for chunk in content_chunks)
    assert final_chunk.delta == ""
    assert final_chunk.is_final is True
    assert final_chunk.finish_reason is FinishReason.STOP
    assert final_chunk.usage is None
    assert provider.recorded_requests == (request,)


@pytest.mark.asyncio
async def test_stream_generate_returns_fixed_chunks() -> None:
    provider = MockProvider(response_text="abcdefghijklmnopq")

    chunks = [chunk async for chunk in provider.stream_generate(_request())]

    assert tuple(chunk.delta for chunk in chunks) == (
        "abcdefgh",
        "ijklmnop",
        "q",
        "",
    )
    assert tuple(chunk.sequence for chunk in chunks) == (0, 1, 2, 3)
    assert chunks[-1].is_final is True
    await provider.aclose()


@pytest.mark.asyncio
async def test_empty_response_returns_complete_result_and_final_chunk() -> None:
    provider = MockProvider(response_text="")
    request = _request()

    response = await provider.generate(request)
    chunks = [chunk async for chunk in provider.stream_generate(request)]

    assert response.text == ""
    assert response.finish_reason is FinishReason.STOP
    assert len(chunks) == 1
    assert chunks[0].delta == ""
    assert chunks[0].sequence == 0
    assert chunks[0].is_final is True
    assert chunks[0].finish_reason is FinishReason.STOP
    assert provider.recorded_requests == (request, request)
    await provider.aclose()


ERROR_CASES: tuple[tuple[MockErrorMode, type[LLMException]], ...] = (
    (MockErrorMode.TIMEOUT, ProviderTimeout),
    (MockErrorMode.AUTHENTICATION, ProviderAuthenticationError),
    (MockErrorMode.RATE_LIMIT, ProviderRateLimitError),
    (MockErrorMode.UNAVAILABLE, ProviderUnavailable),
)


@pytest.mark.asyncio
@pytest.mark.parametrize(("error_mode", "exception_type"), ERROR_CASES)
async def test_generate_raises_configured_normalized_error(
    error_mode: MockErrorMode,
    exception_type: type[LLMException],
) -> None:
    provider = MockProvider(error_mode=error_mode)
    request = _request()

    with pytest.raises(exception_type) as raised:
        await provider.generate(request)

    error = raised.value
    assert error.provider_name == "mock"
    assert error.provider_request_id == "mock-request-000001"
    assert provider.recorded_requests == (request,)
    if isinstance(error, ProviderRateLimitError):
        assert error.retry_after_seconds == 1.0


@pytest.mark.asyncio
@pytest.mark.parametrize(("error_mode", "exception_type"), ERROR_CASES)
async def test_stream_generate_raises_configured_normalized_error(
    error_mode: MockErrorMode,
    exception_type: type[LLMException],
) -> None:
    provider = MockProvider(error_mode=error_mode)
    request = _request()

    with pytest.raises(exception_type):
        _ = [chunk async for chunk in provider.stream_generate(request)]

    assert provider.recorded_requests == (request,)
