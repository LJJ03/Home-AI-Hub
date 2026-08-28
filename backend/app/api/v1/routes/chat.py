"""Version 1 HTTP adapter for stateless Chat completions."""

from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Annotated, Protocol, runtime_checkable

from fastapi import APIRouter, Depends, status
from fastapi.responses import StreamingResponse

from app.api.dependencies.chat import get_chat_service
from app.api.error_mapping.llm import map_llm_exception
from app.llm.exceptions import LLMException
from app.schemas.chat import (
    ChatRequest,
    ChatResponse,
    ChatStreamErrorEvent,
    ChatStreamEvent,
)
from app.services import ChatService


router = APIRouter(prefix="/chat", tags=["chat"])


@runtime_checkable
class _AsyncClosable(Protocol):
    """Identify a Chat event iterator that supports asynchronous cleanup."""

    async def aclose(self) -> None:
        """Release resources owned by the stream."""

        ...


@router.post(
    "/completions",
    response_model=ChatResponse,
    status_code=status.HTTP_200_OK,
    summary="Create a Chat completion",
)
async def create_chat_completion(
    request: ChatRequest,
    chat_service: Annotated[ChatService, Depends(get_chat_service)],
) -> ChatResponse | StreamingResponse:
    """Return one stateless JSON or SSE completion through ChatService."""

    if request.stream:
        return await _create_streaming_response(request, chat_service)

    try:
        return await chat_service.complete(request)
    except LLMException as exception:
        raise map_llm_exception(
            exception,
            request_id=request.request_id,
        ) from None


async def _create_streaming_response(
    request: ChatRequest,
    chat_service: ChatService,
) -> StreamingResponse:
    """Prefetch one event so startup failures retain normal HTTP semantics."""

    events = chat_service.stream(request)
    try:
        first_event = await anext(events)
    except LLMException as exception:
        await _close_stream(events)
        raise map_llm_exception(
            exception,
            request_id=request.request_id,
        ) from None
    except BaseException:
        await _close_stream(events)
        raise

    return StreamingResponse(
        _encode_event_stream(first_event, events),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


async def _encode_event_stream(
    first_event: ChatStreamEvent,
    events: AsyncIterator[ChatStreamEvent],
) -> AsyncIterator[bytes]:
    """Encode Chat events as SSE and sanitize failures after headers start."""

    request_id = first_event.request_id
    try:
        yield _encode_sse_event(first_event)
        async for event in events:
            if event.request_id != request_id:
                raise RuntimeError("Chat stream request ID changed")
            yield _encode_sse_event(event)
    except LLMException as exception:
        yield _encode_sse_event(
            _to_stream_error_event(exception, request_id=request_id)
        )
    except Exception:
        yield _encode_sse_event(
            ChatStreamErrorEvent(
                request_id=request_id,
                code="internal_server_error",
                message="An unexpected error occurred",
                created_at=datetime.now(UTC),
            )
        )
    finally:
        await _close_stream(events)


def _to_stream_error_event(
    exception: LLMException,
    *,
    request_id: str,
) -> ChatStreamErrorEvent:
    """Reuse the centralized safe mapping after an SSE response has started."""

    mapped_error = map_llm_exception(exception, request_id=request_id)
    retry_after_seconds: float | None = None
    if isinstance(mapped_error.details, dict):
        retry_value = mapped_error.details.get("retry_after_seconds")
        if isinstance(retry_value, (int, float)) and not isinstance(retry_value, bool):
            retry_after_seconds = float(retry_value)
    return ChatStreamErrorEvent(
        request_id=request_id,
        code=mapped_error.code,
        message=mapped_error.message,
        retry_after_seconds=retry_after_seconds,
        created_at=datetime.now(UTC),
    )


def _encode_sse_event(event: ChatStreamEvent) -> bytes:
    """Serialize one validated event without logging or buffering its content."""

    return (
        f"event: {event.event}\n"
        f"data: {event.model_dump_json()}\n\n"
    ).encode("utf-8")


async def _close_stream(events: AsyncIterator[ChatStreamEvent]) -> None:
    """Close an event iterator when supported."""

    if isinstance(events, _AsyncClosable):
        await events.aclose()


__all__ = ("router",)
