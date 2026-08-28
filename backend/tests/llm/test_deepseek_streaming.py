"""Offline streaming contract tests for the DeepSeek HTTP adapter."""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
from collections.abc import AsyncIterator, Sequence
from typing import Any

import httpx
import pytest

from app.llm import (
    FinishReason,
    LLMException,
    LLMMessage,
    LLMRequest,
    LLMStreamChunk,
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


SENSITIVE_API_KEY = "deepseek-stream-secret-never-render"
SENSITIVE_PROMPT = "deepseek stream prompt never render"
SENSITIVE_RESPONSE = "deepseek raw stream error never render"
STREAM_REQUEST_ID = "deepseek-stream-request-id"
STREAM_MODEL = "deepseek-stream-response-model"


class RecordingByteStream(httpx.AsyncByteStream):
    """Yield in-memory bytes and expose deterministic close/cancel state."""

    def __init__(
        self,
        chunks: Sequence[bytes],
        *,
        block_after_yields: int | None = None,
        failure_type: type[httpx.RequestError] | None = None,
    ) -> None:
        self._chunks = tuple(chunks)
        self._block_after_yields = block_after_yields
        self._failure_type = failure_type
        self.blocked = asyncio.Event()
        self.release = asyncio.Event()
        self.yield_count = 0
        self.close_calls = 0

    async def __aiter__(self) -> AsyncIterator[bytes]:
        for chunk in self._chunks:
            self.yield_count += 1
            yield chunk
            if self.yield_count == self._block_after_yields:
                self.blocked.set()
                await self.release.wait()
        if self._failure_type is not None:
            raise self._failure_type(
                f"midstream {SENSITIVE_API_KEY} {SENSITIVE_RESPONSE}",
                request=httpx.Request(
                    "POST",
                    "https://offline-transport.example.test",
                ),
            )

    async def aclose(self) -> None:
        self.close_calls += 1
        self.release.set()


def _settings(**overrides: Any) -> LLMSettings:
    values: dict[str, Any] = {
        "provider": "deepseek",
        "default_model": "generic-stream-fallback-model",
        "timeout_seconds": 30.0,
        "default_temperature": 0.3,
        "default_max_tokens": 640,
        "deepseek_api_key": SENSITIVE_API_KEY,
        "deepseek_base_url": "https://deepseek-stream.example.test/v1",
        "deepseek_default_model": "deepseek-stream-default-model",
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
        "correlation_id": "deepseek-stream-correlation",
    }
    values.update(overrides)
    return LLMRequest(**values)


def _provider(
    handler: Any,
    *,
    settings: LLMSettings | None = None,
) -> DeepSeekProvider:
    configured_settings = settings or _settings()
    client = LLMHTTPClient(
        configured_settings,
        transport=httpx.MockTransport(handler),
    )
    return DeepSeekProvider(configured_settings, http_client=client)


def _event(payload: Any) -> bytes:
    data = json.dumps(payload, separators=(",", ":"))
    return f"data: {data}\n\n".encode()


def _done() -> bytes:
    return b"data: [DONE]\n\n"


def _chunk_payload(
    *,
    content: str | None = None,
    finish_reason: str | None = None,
    request_id: str = STREAM_REQUEST_ID,
    model: str = STREAM_MODEL,
    delta_overrides: dict[str, Any] | None = None,
) -> dict[str, Any]:
    delta: dict[str, Any] = {}
    if content is not None:
        delta["content"] = content
    if delta_overrides:
        delta.update(delta_overrides)
    return {
        "id": request_id,
        "model": model,
        "choices": [
            {
                "index": 0,
                "delta": delta,
                "finish_reason": finish_reason,
            }
        ],
    }


def _usage_payload() -> dict[str, Any]:
    return {
        "id": STREAM_REQUEST_ID,
        "model": STREAM_MODEL,
        "choices": [],
        "usage": {
            "prompt_tokens": 13,
            "completion_tokens": 5,
            "total_tokens": 18,
        },
    }


def _success_stream(*, include_usage: bool = True) -> bytes:
    frames = [
        b": keep-alive\n\n",
        _event(_chunk_payload(content="Hello")),
        _event(_chunk_payload(content=" world")),
        _event(_chunk_payload(finish_reason="stop")),
    ]
    if include_usage:
        frames.append(_event(_usage_payload()))
    frames.append(_done())
    return b"".join(frames)


async def _collect(provider: DeepSeekProvider) -> list[LLMStreamChunk]:
    return [chunk async for chunk in provider.stream_generate(_request())]


def _assert_safe_error(error: LLMException) -> None:
    rendered = f"{error!s}\n{error!r}"
    assert SENSITIVE_API_KEY not in rendered
    assert SENSITIVE_PROMPT not in rendered
    assert SENSITIVE_RESPONSE not in rendered
    assert "Authorization" not in rendered
    assert "httpx" not in rendered.lower()
    assert error.provider_request_id is None
    assert error.__cause__ is None
    assert error.__context__ is None
    assert not hasattr(error, "request")
    assert not hasattr(error, "response")


@pytest.mark.asyncio
async def test_stream_request_uses_frozen_fields_and_stream_options() -> None:
    captured: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(200, content=_success_stream())

    provider = _provider(handler)
    request = _request(
        model_name="request-selected-stream-model",
        temperature=0.75,
        max_tokens=321,
    )
    try:
        chunks = [
            chunk async for chunk in provider.stream_generate(request)
        ]
    finally:
        await provider.aclose()

    assert chunks[-1].is_final is True
    outgoing = captured[0]
    payload = json.loads(outgoing.content)
    assert outgoing.method == "POST"
    assert str(outgoing.url) == (
        "https://deepseek-stream.example.test/v1/chat/completions"
    )
    actual_digest = hashlib.sha256(
        outgoing.headers["Authorization"].encode()
    ).digest()
    expected_digest = hashlib.sha256(
        f"Bearer {SENSITIVE_API_KEY}".encode()
    ).digest()
    assert hmac.compare_digest(actual_digest, expected_digest)
    assert outgoing.headers["Content-Type"].startswith("application/json")
    assert outgoing.headers["Accept"] == "text/event-stream"
    assert payload == {
        "messages": [
            {"role": "system", "content": "System instruction"},
            {"role": "user", "content": SENSITIVE_PROMPT},
        ],
        "model": "request-selected-stream-model",
        "temperature": 0.75,
        "max_tokens": 321,
        "stream": True,
        "stream_options": {"include_usage": True},
    }
    assert set(payload) == {
        "messages",
        "model",
        "temperature",
        "max_tokens",
        "stream",
        "stream_options",
    }


@pytest.mark.asyncio
async def test_stream_defaults_come_from_configuration() -> None:
    captured_payloads: list[dict[str, Any]] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        captured_payloads.append(json.loads(request.content))
        return httpx.Response(200, content=_success_stream())

    provider = _provider(handler)
    try:
        await _collect(provider)
    finally:
        await provider.aclose()

    assert captured_payloads[0]["model"] == "deepseek-stream-default-model"
    assert captured_payloads[0]["temperature"] == 0.3
    assert captured_payloads[0]["max_tokens"] == 640


@pytest.mark.asyncio
async def test_content_chunks_and_final_metadata_are_normalized() -> None:
    raw_stream = _success_stream()
    source = RecordingByteStream(
        [raw_stream[:17], raw_stream[17:73], raw_stream[73:]]
    )

    async def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, stream=source)

    provider = _provider(handler)
    try:
        chunks = await _collect(provider)
    finally:
        await provider.aclose()

    assert [chunk.sequence for chunk in chunks] == [0, 1, 2]
    assert [chunk.delta for chunk in chunks] == ["Hello", " world", ""]
    assert all(chunk.provider_name == "deepseek" for chunk in chunks)
    assert all(chunk.model_name == STREAM_MODEL for chunk in chunks)
    assert all(
        chunk.provider_request_id == STREAM_REQUEST_ID for chunk in chunks
    )
    assert chunks[0].is_final is False
    assert chunks[1].is_final is False
    assert chunks[2].is_final is True
    assert chunks[2].finish_reason is FinishReason.STOP
    assert chunks[2].usage is not None
    assert chunks[2].usage.input_tokens == 13
    assert chunks[2].usage.output_tokens == 5
    assert chunks[2].usage.total_tokens == 18
    assert source.close_calls >= 1


@pytest.mark.asyncio
async def test_reasoning_content_is_ignored_and_empty_output_still_finishes() -> None:
    data = b"".join(
        [
            _event(
                _chunk_payload(
                    finish_reason="stop",
                    delta_overrides={
                        "reasoning_content": "private chain of thought"
                    },
                )
            ),
            _done(),
        ]
    )
    provider = _provider(lambda _: httpx.Response(200, content=data))
    try:
        chunks = await _collect(provider)
    finally:
        await provider.aclose()

    assert len(chunks) == 1
    assert chunks[0].sequence == 0
    assert chunks[0].delta == ""
    assert chunks[0].is_final is True
    assert chunks[0].usage is None
    assert "private chain of thought" not in repr(chunks[0])


@pytest.mark.asyncio
async def test_usage_only_event_does_not_emit_text_chunk() -> None:
    provider = _provider(
        lambda _: httpx.Response(200, content=_success_stream())
    )
    try:
        chunks = await _collect(provider)
    finally:
        await provider.aclose()

    assert len(chunks) == 3
    assert [chunk.delta for chunk in chunks[:-1]] == ["Hello", " world"]
    assert chunks[-1].usage is not None


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("vendor_reason", "expected_reason"),
    [
        ("length", FinishReason.LENGTH),
        ("content_filter", FinishReason.CONTENT_FILTER),
        ("future_reason", FinishReason.UNKNOWN),
    ],
)
async def test_stream_finish_reason_is_normalized(
    vendor_reason: str,
    expected_reason: FinishReason,
) -> None:
    data = _event(_chunk_payload(finish_reason=vendor_reason)) + _done()
    provider = _provider(lambda _: httpx.Response(200, content=data))
    try:
        chunks = await _collect(provider)
    finally:
        await provider.aclose()

    assert chunks[-1].finish_reason is expected_reason


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "unsupported_field",
    ["tool_calls", "tool_call", "function_call"],
)
async def test_tool_and_function_deltas_are_rejected(
    unsupported_field: str,
) -> None:
    data = _event(
        _chunk_payload(delta_overrides={unsupported_field: [{"unsafe": True}]})
    )
    provider = _provider(lambda _: httpx.Response(200, content=data))
    try:
        with pytest.raises(ProviderInvalidResponse) as exc_info:
            await _collect(provider)
    finally:
        await provider.aclose()

    _assert_safe_error(exc_info.value)


@pytest.mark.asyncio
@pytest.mark.parametrize("finish_reason", ["tool_calls", "function_call"])
async def test_tool_and_function_finish_reasons_are_rejected(
    finish_reason: str,
) -> None:
    data = _event(_chunk_payload(finish_reason=finish_reason))
    provider = _provider(lambda _: httpx.Response(200, content=data))
    try:
        with pytest.raises(ProviderInvalidResponse):
            await _collect(provider)
    finally:
        await provider.aclose()


@pytest.mark.asyncio
async def test_insufficient_resource_finish_maps_to_unavailable() -> None:
    data = _event(
        _chunk_payload(finish_reason="insufficient_system_resource")
    )
    provider = _provider(lambda _: httpx.Response(200, content=data))
    try:
        with pytest.raises(ProviderUnavailable) as exc_info:
            await _collect(provider)
    finally:
        await provider.aclose()

    _assert_safe_error(exc_info.value)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "data",
    [
        f"data: {SENSITIVE_RESPONSE}\n\n".encode(),
        _event([]),
        _event({}),
        _event({"choices": [{}, {}]}),
        _event({"choices": [{"delta": None}]}),
        _event(
            {
                "choices": [
                    {"delta": {"content": 42}, "finish_reason": None}
                ]
            }
        ),
        _event(
            {
                "choices": [],
                "usage": {"prompt_tokens": -1},
            }
        ),
        b"data: \xff\n\n",
        b'data: {"choices":[]}',
    ],
)
async def test_malformed_stream_data_maps_to_invalid_response(
    data: bytes,
) -> None:
    provider = _provider(lambda _: httpx.Response(200, content=data))
    try:
        with pytest.raises(ProviderInvalidResponse) as exc_info:
            await _collect(provider)
    finally:
        await provider.aclose()

    _assert_safe_error(exc_info.value)


@pytest.mark.asyncio
async def test_stream_without_done_is_invalid_even_after_finish_reason() -> None:
    data = _event(_chunk_payload(finish_reason="stop"))
    provider = _provider(lambda _: httpx.Response(200, content=data))
    try:
        with pytest.raises(ProviderInvalidResponse):
            await _collect(provider)
    finally:
        await provider.aclose()


@pytest.mark.asyncio
async def test_done_without_finish_reason_is_invalid() -> None:
    data = _event(_chunk_payload(content="partial")) + _done()
    provider = _provider(lambda _: httpx.Response(200, content=data))
    try:
        with pytest.raises(ProviderInvalidResponse):
            await _collect(provider)
    finally:
        await provider.aclose()


@pytest.mark.asyncio
@pytest.mark.parametrize("identity_field", ["id", "model"])
async def test_inconsistent_stream_identity_is_invalid(
    identity_field: str,
) -> None:
    first = _chunk_payload(content="first")
    second = _chunk_payload(content="second")
    second[identity_field] = f"different-{identity_field}"
    data = _event(first) + _event(second)
    provider = _provider(lambda _: httpx.Response(200, content=data))
    try:
        with pytest.raises(ProviderInvalidResponse):
            await _collect(provider)
    finally:
        await provider.aclose()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("status_code", "exception_type"),
    [
        (400, ProviderConfigurationError),
        (401, ProviderAuthenticationError),
        (408, ProviderTimeout),
        (429, ProviderRateLimitError),
        (500, ProviderUnavailable),
        (503, ProviderUnavailable),
    ],
)
async def test_stream_http_status_uses_unified_mapping(
    status_code: int,
    exception_type: type[LLMException],
) -> None:
    source = RecordingByteStream([SENSITIVE_RESPONSE.encode()])

    async def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            status_code,
            headers={"Retry-After": "2.5"},
            stream=source,
        )

    provider = _provider(handler)
    try:
        with pytest.raises(exception_type) as exc_info:
            await _collect(provider)
    finally:
        await provider.aclose()

    if isinstance(exc_info.value, ProviderRateLimitError):
        assert exc_info.value.retry_after_seconds == 2.5
    _assert_safe_error(exc_info.value)
    assert source.close_calls >= 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("httpx_error_type", "exception_type"),
    [
        (httpx.ReadTimeout, ProviderTimeout),
        (httpx.ConnectError, ProviderUnavailable),
    ],
)
async def test_stream_transport_errors_are_normalized(
    httpx_error_type: type[httpx.RequestError],
    exception_type: type[LLMException],
) -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        raise httpx_error_type(
            f"transport {SENSITIVE_API_KEY} {SENSITIVE_PROMPT}",
            request=request,
        )

    provider = _provider(handler)
    try:
        with pytest.raises(exception_type) as exc_info:
            await _collect(provider)
    finally:
        await provider.aclose()

    _assert_safe_error(exc_info.value)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("httpx_error_type", "exception_type"),
    [
        (httpx.ReadTimeout, ProviderTimeout),
        (httpx.ReadError, ProviderUnavailable),
    ],
)
async def test_midstream_transport_error_releases_response(
    httpx_error_type: type[httpx.RequestError],
    exception_type: type[LLMException],
) -> None:
    source = RecordingByteStream(
        [_event(_chunk_payload(content="first"))],
        failure_type=httpx_error_type,
    )

    async def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, stream=source)

    provider = _provider(handler)
    iterator = provider.stream_generate(_request())
    try:
        assert (await anext(iterator)).delta == "first"
        with pytest.raises(exception_type) as exc_info:
            await anext(iterator)
    finally:
        await iterator.aclose()
        await provider.aclose()

    _assert_safe_error(exc_info.value)
    assert source.close_calls >= 1


@pytest.mark.asyncio
async def test_response_and_iterator_close_after_midstream_error() -> None:
    source = RecordingByteStream(
        [_event(_chunk_payload(content="first")), b"data: not-json\n\n"]
    )

    async def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, stream=source)

    provider = _provider(handler)
    iterator = provider.stream_generate(_request())
    try:
        first = await anext(iterator)
        assert first.delta == "first"
        with pytest.raises(ProviderInvalidResponse):
            await anext(iterator)
    finally:
        await iterator.aclose()
        await provider.aclose()

    assert source.close_calls >= 1


@pytest.mark.asyncio
async def test_stream_is_incremental_and_early_close_releases_response() -> None:
    source = RecordingByteStream(
        [
            _event(_chunk_payload(content="first")),
            _event(_chunk_payload(content="second")),
            _event(_chunk_payload(finish_reason="stop")),
            _done(),
        ]
    )

    async def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, stream=source)

    provider = _provider(handler)
    iterator = provider.stream_generate(_request())
    try:
        first = await anext(iterator)
        assert first.delta == "first"
        assert source.yield_count == 1
    finally:
        await iterator.aclose()
        await provider.aclose()

    assert source.yield_count == 1
    assert source.close_calls >= 1


@pytest.mark.asyncio
async def test_cancelled_error_propagates_and_releases_response() -> None:
    source = RecordingByteStream(
        [
            _event(_chunk_payload(content="first")),
            _event(_chunk_payload(content="never returned")),
        ],
        block_after_yields=1,
    )

    async def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, stream=source)

    provider = _provider(handler)
    task = asyncio.create_task(_collect(provider))
    try:
        await asyncio.wait_for(source.blocked.wait(), timeout=1.0)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    finally:
        source.release.set()
        await provider.aclose()

    assert source.close_calls >= 1


@pytest.mark.asyncio
async def test_streaming_provider_close_remains_idempotent() -> None:
    class RecordingTransport(httpx.MockTransport):
        def __init__(self) -> None:
            super().__init__(
                lambda _: httpx.Response(200, content=_success_stream())
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

    await _collect(provider)
    await provider.aclose()
    await provider.aclose()

    assert transport.close_calls == 1
