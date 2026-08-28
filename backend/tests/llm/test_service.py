"""Unit tests for the vendor-neutral LLM service boundary."""

import asyncio
from collections.abc import AsyncIterator

import pytest

from app.llm import (
    FinishReason,
    LLMMessage,
    LLMProvider,
    LLMRequest,
    LLMResponse,
    LLMStreamChunk,
    MessageRole,
    ProviderUnavailable,
)
from app.llm.service import LLMService


def _request() -> LLMRequest:
    return LLMRequest(
        messages=(LLMMessage(role=MessageRole.USER, content="Service input"),),
        correlation_id="service-test",
    )


class TrackingStream(AsyncIterator[LLMStreamChunk]):
    """Expose deterministic chunks and observable asynchronous cleanup."""

    def __init__(self, chunks: tuple[LLMStreamChunk, ...]) -> None:
        self._chunks = iter(chunks)
        self.aclose_calls = 0

    def __aiter__(self) -> AsyncIterator[LLMStreamChunk]:
        return self

    async def __anext__(self) -> LLMStreamChunk:
        try:
            return next(self._chunks)
        except StopIteration as error:
            raise StopAsyncIteration from error

    async def aclose(self) -> None:
        self.aclose_calls += 1


class RecordingProvider(LLMProvider):
    """Record service delegation without external resources."""

    def __init__(self) -> None:
        self.generate_requests: list[LLMRequest] = []
        self.stream_requests: list[LLMRequest] = []
        self.last_stream: TrackingStream | None = None
        self.aclose_calls = 0

    @property
    def provider_name(self) -> str:
        return "recording"

    @property
    def default_model(self) -> str:
        return "recording-model"

    async def generate(self, request: LLMRequest) -> LLMResponse:
        self.generate_requests.append(request)
        return LLMResponse(
            text="Recorded response",
            provider_name=self.provider_name,
            model_name=self.default_model,
            finish_reason=FinishReason.STOP,
            provider_request_id="recording-request",
        )

    def stream_generate(self, request: LLMRequest) -> AsyncIterator[LLMStreamChunk]:
        self.stream_requests.append(request)
        self.last_stream = TrackingStream(
            (
                LLMStreamChunk(
                    sequence=0,
                    delta="Recorded ",
                    provider_name=self.provider_name,
                    model_name=self.default_model,
                    provider_request_id="recording-stream",
                ),
                LLMStreamChunk(
                    sequence=1,
                    delta="response",
                    provider_name=self.provider_name,
                    model_name=self.default_model,
                    provider_request_id="recording-stream",
                ),
                LLMStreamChunk(
                    sequence=2,
                    provider_name=self.provider_name,
                    model_name=self.default_model,
                    is_final=True,
                    finish_reason=FinishReason.STOP,
                    provider_request_id="recording-stream",
                ),
            )
        )
        return self.last_stream

    async def aclose(self) -> None:
        self.aclose_calls += 1


class FailingProvider(RecordingProvider):
    """Raise one preconstructed normalized exception from generate."""

    def __init__(self, error: ProviderUnavailable) -> None:
        super().__init__()
        self._error = error

    async def generate(self, request: LLMRequest) -> LLMResponse:
        self.generate_requests.append(request)
        raise self._error


class BlockingStream(AsyncIterator[LLMStreamChunk]):
    """Block iteration until its consumer is cancelled."""

    def __init__(self) -> None:
        self.started = asyncio.Event()
        self.aclose_calls = 0

    def __aiter__(self) -> AsyncIterator[LLMStreamChunk]:
        return self

    async def __anext__(self) -> LLMStreamChunk:
        self.started.set()
        await asyncio.Event().wait()
        raise StopAsyncIteration

    async def aclose(self) -> None:
        self.aclose_calls += 1


class BlockingProvider(RecordingProvider):
    """Return a cancellable stream with observable cleanup."""

    def __init__(self) -> None:
        super().__init__()
        self.blocking_stream = BlockingStream()

    def stream_generate(self, request: LLMRequest) -> AsyncIterator[LLMStreamChunk]:
        self.stream_requests.append(request)
        return self.blocking_stream


@pytest.mark.asyncio
async def test_generate_delegates_to_provider_interface() -> None:
    provider = RecordingProvider()
    service = LLMService(provider)
    request = _request()

    response = await service.generate(request)

    assert response.text == "Recorded response"
    assert provider.generate_requests == [request]


@pytest.mark.asyncio
async def test_generate_preserves_normalized_provider_exception() -> None:
    error = ProviderUnavailable(
        "Provider unavailable",
        provider_name="recording",
    )
    provider = FailingProvider(error)
    service = LLMService(provider)

    with pytest.raises(ProviderUnavailable) as raised:
        await service.generate(_request())

    assert raised.value is error


@pytest.mark.asyncio
async def test_stream_generate_forwards_chunks_and_closes_upstream() -> None:
    provider = RecordingProvider()
    service = LLMService(provider)
    request = _request()

    chunks = [chunk async for chunk in service.stream_generate(request)]

    assert "".join(chunk.delta for chunk in chunks) == "Recorded response"
    assert provider.stream_requests == [request]
    assert provider.last_stream is not None
    assert provider.last_stream.aclose_calls == 1


@pytest.mark.asyncio
async def test_stream_cancellation_propagates_and_closes_upstream() -> None:
    provider = BlockingProvider()
    service = LLMService(provider)
    stream = service.stream_generate(_request())

    async def consume_next_chunk() -> LLMStreamChunk:
        return await anext(stream)

    consumer = asyncio.create_task(consume_next_chunk())
    await provider.blocking_stream.started.wait()
    consumer.cancel()

    with pytest.raises(asyncio.CancelledError):
        await consumer

    assert provider.blocking_stream.aclose_calls == 1


@pytest.mark.asyncio
async def test_aclose_delegates_to_provider() -> None:
    provider = RecordingProvider()
    service = LLMService(provider)

    await service.aclose()

    assert provider.aclose_calls == 1


def test_diagnose_returns_local_metadata_only() -> None:
    provider = RecordingProvider()
    service = LLMService(provider)

    diagnostics = service.diagnose()

    assert diagnostics.provider_name == "recording"
    assert diagnostics.default_model == "recording-model"
    assert provider.generate_requests == []
    assert provider.stream_requests == []
