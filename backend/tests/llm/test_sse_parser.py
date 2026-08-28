"""Offline protocol tests for the incremental internal SSE parser."""

from __future__ import annotations

import ast
import asyncio
from collections.abc import AsyncIterator
from pathlib import Path

import pytest

from app.llm.http.sse import SSEEvent, SSEProtocolError, parse_sse


SSE_MODULE_PATH = Path(__file__).resolve().parents[2] / "app/llm/http/sse.py"


async def _chunks(*values: str | bytes) -> AsyncIterator[str | bytes]:
    for value in values:
        yield value


async def _collect(*values: str | bytes) -> list[SSEEvent]:
    return [event async for event in parse_sse(_chunks(*values))]


class _RecordingIterator:
    def __init__(self, values: list[str | bytes]) -> None:
        self._values = iter(values)
        self.items_read = 0
        self.close_calls = 0

    def __aiter__(self) -> _RecordingIterator:
        return self

    async def __anext__(self) -> str | bytes:
        try:
            value = next(self._values)
        except StopIteration:
            raise StopAsyncIteration from None
        self.items_read += 1
        return value

    async def aclose(self) -> None:
        self.close_calls += 1


class _BlockingIterator:
    def __init__(self) -> None:
        self.started = asyncio.Event()
        self.closed = False

    def __aiter__(self) -> _BlockingIterator:
        return self

    async def __anext__(self) -> str:
        self.started.set()
        await asyncio.Event().wait()
        raise StopAsyncIteration

    async def aclose(self) -> None:
        self.closed = True


@pytest.mark.asyncio
async def test_single_data_event_is_parsed() -> None:
    events = await _collect("data: hello\n\n")

    assert events == [SSEEvent(data="hello", is_done=False)]


@pytest.mark.asyncio
async def test_multiline_data_is_joined_with_newlines() -> None:
    events = await _collect("data: first line\ndata: second line\n\n")

    assert events == [
        SSEEvent(data="first line\nsecond line", is_done=False)
    ]


@pytest.mark.asyncio
async def test_empty_line_terminates_each_event_in_order() -> None:
    events = await _collect("data: one\n\ndata: two\n\n")

    assert events == [
        SSEEvent(data="one", is_done=False),
        SSEEvent(data="two", is_done=False),
    ]


@pytest.mark.asyncio
async def test_comments_and_keep_alive_frames_are_ignored() -> None:
    events = await _collect(
        ": keep-alive\n\n",
        "event: message\nid: local-id\ndata: payload\n\n",
    )

    assert events == [SSEEvent(data="payload", is_done=False)]


@pytest.mark.asyncio
async def test_done_marker_is_identified_without_supplier_semantics() -> None:
    events = await _collect("data: [DONE]\n\n")

    assert events == [SSEEvent(data="[DONE]", is_done=True)]


@pytest.mark.asyncio
@pytest.mark.parametrize("frame", ["data:\n\n", "data\n\n"])
async def test_empty_data_is_emitted_as_an_empty_event(frame: str) -> None:
    events = await _collect(frame)

    assert events == [SSEEvent(data="", is_done=False)]


@pytest.mark.asyncio
async def test_arbitrarily_fragmented_crlf_input_is_parsed() -> None:
    events = await _collect("da", "ta: frag", "mented\r", "\n\r", "\n")

    assert events == [SSEEvent(data="fragmented", is_done=False)]


@pytest.mark.asyncio
async def test_split_utf8_bytes_are_decoded_incrementally() -> None:
    encoded = "data: 家庭助手\n\n".encode("utf-8")
    events = await _collect(encoded[:8], encoded[8:11], encoded[11:])

    assert events == [SSEEvent(data="家庭助手", is_done=False)]


@pytest.mark.asyncio
async def test_json_looking_data_remains_unparsed_text() -> None:
    payload = '{"choices":[{"delta":"text"}]}'
    events = await _collect(f"data: {payload}\n\n")

    assert events == [SSEEvent(data=payload, is_done=False)]


@pytest.mark.asyncio
async def test_invalid_utf8_fails_with_safe_protocol_error() -> None:
    with pytest.raises(SSEProtocolError) as exc_info:
        await _collect(b"data: \xff\n\n")

    assert "\\xff" not in str(exc_info.value)


@pytest.mark.asyncio
async def test_truncated_event_fails_instead_of_silently_emitting() -> None:
    with pytest.raises(SSEProtocolError, match="event boundary"):
        await _collect("data: incomplete")


@pytest.mark.asyncio
async def test_event_size_is_bounded_without_buffering_the_full_stream() -> None:
    with pytest.raises(SSEProtocolError, match="safe size limit"):
        async for _ in parse_sse(
            _chunks("data: payload-too-large\n\n"),
            max_event_characters=4,
        ):
            pass


@pytest.mark.asyncio
async def test_parser_releases_source_after_normal_completion() -> None:
    source = _RecordingIterator(["data: complete\n\n"])

    events = [event async for event in parse_sse(source)]

    assert events == [SSEEvent(data="complete", is_done=False)]
    assert source.close_calls == 1


@pytest.mark.asyncio
async def test_parser_releases_source_after_protocol_error() -> None:
    source = _RecordingIterator([b"data: \xff\n\n"])

    with pytest.raises(SSEProtocolError):
        async for _ in parse_sse(source):
            pass

    assert source.close_calls == 1


@pytest.mark.asyncio
async def test_early_consumer_close_releases_source_without_prefetching() -> None:
    source = _RecordingIterator(
        ["data: first\n\n", "data: second\n\n"]
    )
    events = parse_sse(source)

    first = await anext(events)
    assert first == SSEEvent(data="first", is_done=False)
    assert source.items_read == 1

    await events.aclose()
    assert source.close_calls == 1


@pytest.mark.asyncio
async def test_cancelled_error_propagates_and_releases_source() -> None:
    source = _BlockingIterator()

    async def consume() -> None:
        async for _ in parse_sse(source):
            pass

    task = asyncio.create_task(consume())
    await source.started.wait()
    task.cancel()

    with pytest.raises(asyncio.CancelledError):
        await task

    assert source.closed is True


def test_sse_parser_has_only_protocol_level_dependencies() -> None:
    source = SSE_MODULE_PATH.read_text(encoding="utf-8")
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
        "httpx",
        "json",
        "app.api",
        "app.db",
        "app.models",
        "app.repositories",
        "app.services",
        "app.llm.providers",
        "openai",
        "deepseek",
    )

    assert not any(
        imported == prefix or imported.startswith(f"{prefix}.")
        for imported in imports
        for prefix in forbidden_prefixes
    )
    assert "LLMStreamChunk" not in source
    assert "api.openai.com" not in source
    assert "api.deepseek.com" not in source
