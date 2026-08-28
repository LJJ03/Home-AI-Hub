"""Stateless application service for complete and streaming Chat completions."""

from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Protocol, runtime_checkable
from uuid import uuid4

from app.llm.exceptions import ProviderInvalidResponse
from app.llm.schemas import (
    LLMMessage,
    LLMRequest,
    LLMResponse,
    LLMStreamChunk,
    MessageRole,
    TokenUsage,
)
from app.llm.service import LLMService
from app.schemas.chat import (
    ChatFinishReason,
    ChatMessage,
    ChatRequest,
    ChatResponse,
    ChatStreamChunkEvent,
    ChatStreamDoneEvent,
    ChatStreamEvent,
    ChatUsage,
)


@runtime_checkable
class _AsyncClosable(Protocol):
    """Identify an upstream stream that supports deterministic cleanup."""

    async def aclose(self) -> None:
        """Release resources owned by the asynchronous iterator."""

        ...


class ChatService:
    """Adapt stateless Chat DTOs to the vendor-neutral LLM service."""

    __slots__ = ("_llm_service",)

    def __init__(self, llm_service: LLMService) -> None:
        self._llm_service = llm_service

    async def complete(self, request: ChatRequest) -> ChatResponse:
        """Generate one complete Chat response without retaining request state."""

        request_id = request.request_id or uuid4().hex
        llm_request = self._to_llm_request(request, request_id=request_id)
        llm_response = await self._llm_service.generate(llm_request)
        return self._to_chat_response(
            llm_response,
            request_id=request_id,
            created_at=datetime.now(UTC),
        )

    def stream(self, request: ChatRequest) -> AsyncIterator[ChatStreamEvent]:
        """Return normalized Chat events without buffering generated content."""

        return self._stream_events(request)

    async def _stream_events(
        self,
        request: ChatRequest,
    ) -> AsyncIterator[ChatStreamEvent]:
        """Translate LLM chunks and close the upstream stream on every exit path."""

        request_id = request.request_id or uuid4().hex
        llm_request = self._to_llm_request(request, request_id=request_id)
        upstream = self._llm_service.stream_generate(llm_request)
        try:
            async for chunk in upstream:
                created_at = datetime.now(UTC)
                if not chunk.is_final:
                    yield self._to_chat_stream_chunk(
                        chunk,
                        request_id=request_id,
                        created_at=created_at,
                    )
                    continue

                done_sequence = chunk.sequence
                if chunk.delta:
                    yield self._to_chat_stream_chunk(
                        chunk,
                        request_id=request_id,
                        created_at=created_at,
                    )
                    done_sequence += 1
                yield self._to_chat_stream_done(
                    chunk,
                    request_id=request_id,
                    sequence=done_sequence,
                    created_at=datetime.now(UTC),
                )
                return

            raise ProviderInvalidResponse(
                "LLM stream ended without a final chunk",
            )
        finally:
            if isinstance(upstream, _AsyncClosable):
                await upstream.aclose()

    @staticmethod
    def _to_llm_request(request: ChatRequest, *, request_id: str) -> LLMRequest:
        """Convert the public Chat request into the frozen LLM contract."""

        return LLMRequest(
            messages=tuple(
                ChatService._to_llm_message(message) for message in request.messages
            ),
            model_name=request.model_name,
            temperature=request.temperature,
            max_tokens=request.max_tokens,
            correlation_id=request_id,
        )

    @staticmethod
    def _to_llm_message(message: ChatMessage) -> LLMMessage:
        """Map one client-safe Chat role to the vendor-neutral LLM role."""

        return LLMMessage(
            role=MessageRole(message.role.value),
            content=message.content,
        )

    @staticmethod
    def _to_chat_response(
        response: LLMResponse,
        *,
        request_id: str,
        created_at: datetime,
    ) -> ChatResponse:
        """Convert a normalized LLM response into the public Chat contract."""

        return ChatResponse(
            answer=response.text,
            provider_name=response.provider_name,
            model_name=response.model_name,
            finish_reason=ChatFinishReason(response.finish_reason.value),
            usage=ChatService._to_chat_usage(response.usage),
            request_id=request_id,
            created_at=created_at,
        )

    @staticmethod
    def _to_chat_stream_chunk(
        chunk: LLMStreamChunk,
        *,
        request_id: str,
        created_at: datetime,
    ) -> ChatStreamChunkEvent:
        """Copy one text delta without exposing provider request metadata."""

        return ChatStreamChunkEvent(
            request_id=request_id,
            sequence=chunk.sequence,
            delta=chunk.delta,
            provider_name=chunk.provider_name,
            model_name=chunk.model_name,
            created_at=created_at,
        )

    @staticmethod
    def _to_chat_stream_done(
        chunk: LLMStreamChunk,
        *,
        request_id: str,
        sequence: int,
        created_at: datetime,
    ) -> ChatStreamDoneEvent:
        """Convert the final LLM chunk into completion metadata."""

        if chunk.finish_reason is None:
            raise ProviderInvalidResponse(
                "Final LLM stream chunk has no finish reason",
            )
        return ChatStreamDoneEvent(
            request_id=request_id,
            sequence=sequence,
            provider_name=chunk.provider_name,
            model_name=chunk.model_name,
            finish_reason=ChatFinishReason(chunk.finish_reason.value),
            usage=ChatService._to_chat_usage(chunk.usage),
            created_at=created_at,
        )

    @staticmethod
    def _to_chat_usage(usage: TokenUsage | None) -> ChatUsage | None:
        """Copy normalized token counts without exposing an LLM usage object."""

        if usage is None:
            return None
        return ChatUsage(
            input_tokens=usage.input_tokens,
            output_tokens=usage.output_tokens,
            total_tokens=usage.total_tokens,
        )


__all__ = ("ChatService",)
