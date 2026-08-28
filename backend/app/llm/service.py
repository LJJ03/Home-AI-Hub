"""Stable, vendor-neutral application boundary for LLM generation."""

from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from app.llm.interfaces import LLMProvider
from app.llm.schemas import LLMRequest, LLMResponse, LLMStreamChunk


@dataclass(frozen=True, slots=True)
class LLMServiceDiagnostics:
    """Describe locally configured provider metadata without remote probing."""

    provider_name: str
    default_model: str


@runtime_checkable
class _AsyncClosable(Protocol):
    """Identify upstream iterators that expose asynchronous cleanup."""

    async def aclose(self) -> None:
        """Release resources held by the iterator."""

        ...


class LLMService:
    """Expose provider-neutral generation operations to application modules."""

    def __init__(self, provider: LLMProvider) -> None:
        self._provider = provider

    def diagnose(self) -> LLMServiceDiagnostics:
        """Return local provider metadata without network activity."""

        return LLMServiceDiagnostics(
            provider_name=self._provider.provider_name,
            default_model=self._provider.default_model,
        )

    async def generate(self, request: LLMRequest) -> LLMResponse:
        """Delegate one complete generation through the provider boundary."""

        return await self._provider.generate(request)

    def stream_generate(self, request: LLMRequest) -> AsyncIterator[LLMStreamChunk]:
        """Return a provider-neutral stream with deterministic cleanup."""

        return self._forward_stream(request)

    async def aclose(self) -> None:
        """Delegate lifecycle shutdown to the owned provider."""

        await self._provider.aclose()

    async def _forward_stream(
        self,
        request: LLMRequest,
    ) -> AsyncIterator[LLMStreamChunk]:
        """Forward chunks and close the upstream iterator on every exit path."""

        upstream = self._provider.stream_generate(request)
        try:
            async for chunk in upstream:
                yield chunk
        finally:
            if isinstance(upstream, _AsyncClosable):
                await upstream.aclose()


__all__ = ("LLMService", "LLMServiceDiagnostics")
