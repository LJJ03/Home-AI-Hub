"""Incremental, provider-neutral parsing for Server-Sent Event frames."""

from __future__ import annotations

import asyncio
import codecs
from collections.abc import AsyncIterable, AsyncIterator
from dataclasses import dataclass
from typing import Literal


DEFAULT_MAX_EVENT_CHARACTERS = 1_048_576


class SSEProtocolError(Exception):
    """Internal safe failure raised for an unusable SSE byte/text stream."""


@dataclass(frozen=True, slots=True)
class SSEEvent:
    """One protocol-level event without supplier-specific interpretation."""

    data: str
    is_done: bool


class SSEParser:
    """Incrementally parse SSE data fields while retaining one pending event."""

    def __init__(
        self,
        *,
        max_event_characters: int = DEFAULT_MAX_EVENT_CHARACTERS,
    ) -> None:
        if max_event_characters < 1:
            raise ValueError("max_event_characters must be positive")

        self._max_event_characters = max_event_characters
        self._buffer = ""
        self._data_lines: list[str] = []
        self._pending_data_characters = 0
        self._input_kind: Literal["bytes", "text"] | None = None
        self._decoder = codecs.getincrementaldecoder("utf-8")(errors="strict")
        self._finished = False

    def feed(self, chunk: str | bytes) -> tuple[SSEEvent, ...]:
        """Consume one arbitrary input chunk and return completed events."""

        if self._finished:
            raise SSEProtocolError("SSE parser is already finalized")

        text = self._decode_chunk(chunk)
        if not text:
            return ()

        self._buffer += text
        events = self._drain_lines(final=False)
        self._guard_pending_size()
        return tuple(events)

    def finalize(self) -> tuple[SSEEvent, ...]:
        """Finish decoding and reject a stream truncated before its boundary."""

        if self._finished:
            return ()

        self._finished = True
        if self._input_kind == "bytes":
            try:
                self._buffer += self._decoder.decode(b"", final=True)
            except UnicodeDecodeError:
                raise SSEProtocolError("SSE stream is not valid UTF-8") from None

        events = self._drain_lines(final=True)
        if self._data_lines:
            raise SSEProtocolError(
                "SSE stream ended before an event boundary"
            )
        return tuple(events)

    def _decode_chunk(self, chunk: str | bytes) -> str:
        if isinstance(chunk, str):
            if self._input_kind == "bytes":
                raise SSEProtocolError(
                    "SSE stream changed its chunk encoding"
                )
            self._input_kind = "text"
            return chunk

        if isinstance(chunk, bytes):
            if self._input_kind == "text":
                raise SSEProtocolError(
                    "SSE stream changed its chunk encoding"
                )
            self._input_kind = "bytes"
            try:
                return self._decoder.decode(chunk, final=False)
            except UnicodeDecodeError:
                raise SSEProtocolError(
                    "SSE stream is not valid UTF-8"
                ) from None

        raise SSEProtocolError("SSE stream yielded an invalid chunk type")

    def _drain_lines(self, *, final: bool) -> list[SSEEvent]:
        events: list[SSEEvent] = []
        while (line := self._extract_line(final=final)) is not None:
            event = self._process_line(line)
            if event is not None:
                events.append(event)
        return events

    def _extract_line(self, *, final: bool) -> str | None:
        for index, character in enumerate(self._buffer):
            if character == "\n":
                line = self._buffer[:index]
                self._buffer = self._buffer[index + 1 :]
                return line

            if character == "\r":
                if index + 1 == len(self._buffer) and not final:
                    return None
                separator_length = (
                    2
                    if index + 1 < len(self._buffer)
                    and self._buffer[index + 1] == "\n"
                    else 1
                )
                line = self._buffer[:index]
                self._buffer = self._buffer[index + separator_length :]
                return line

        if final and self._buffer:
            line = self._buffer
            self._buffer = ""
            return line
        return None

    def _process_line(self, line: str) -> SSEEvent | None:
        if not line:
            if not self._data_lines:
                return None

            data = "\n".join(self._data_lines)
            self._data_lines.clear()
            self._pending_data_characters = 0
            return SSEEvent(data=data, is_done=data == "[DONE]")

        if line.startswith(":"):
            return None

        field, separator, value = line.partition(":")
        if separator and value.startswith(" "):
            value = value[1:]

        if field != "data":
            return None

        if self._data_lines:
            self._pending_data_characters += 1
        self._data_lines.append(value)
        self._pending_data_characters += len(value)
        self._guard_pending_size()
        return None

    def _guard_pending_size(self) -> None:
        pending_size = len(self._buffer) + self._pending_data_characters
        if pending_size > self._max_event_characters:
            raise SSEProtocolError("SSE event exceeds the safe size limit")


async def parse_sse(
    chunks: AsyncIterable[str | bytes],
    *,
    max_event_characters: int = DEFAULT_MAX_EVENT_CHARACTERS,
) -> AsyncIterator[SSEEvent]:
    """Parse an asynchronous stream and always release its iterator."""

    parser = SSEParser(max_event_characters=max_event_characters)
    iterator = chunks.__aiter__()
    failure: BaseException | None = None

    try:
        async for chunk in iterator:
            for event in parser.feed(chunk):
                yield event
        for event in parser.finalize():
            yield event
    except BaseException as exc:
        failure = exc
        raise
    finally:
        close = getattr(iterator, "aclose", None)
        if close is not None:
            try:
                await close()
            except BaseException:
                if failure is None:
                    raise


__all__ = (
    "DEFAULT_MAX_EVENT_CHARACTERS",
    "SSEEvent",
    "SSEParser",
    "SSEProtocolError",
    "parse_sse",
)
