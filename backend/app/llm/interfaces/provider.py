"""Vendor-neutral asynchronous LLM provider interface."""

from collections.abc import AsyncIterator
from typing import Protocol

from app.llm.schemas.request import LLMRequest
from app.llm.schemas.response import LLMResponse, LLMStreamChunk


class LLMProvider(Protocol):
    """Define the strategy contract implemented by every LLM provider."""

    @property
    def provider_name(self) -> str:
        """Return the stable registry name for this provider."""

        ...

    @property
    def default_model(self) -> str:
        """Return the default model selected for this provider instance."""

        ...

    async def generate(self, request: LLMRequest) -> LLMResponse:
        """Generate one complete normalized response."""

        ...

    def stream_generate(self, request: LLMRequest) -> AsyncIterator[LLMStreamChunk]:
        """Return an asynchronous iterator of normalized response chunks."""

        ...

    async def aclose(self) -> None:
        """Release provider-owned clients and other asynchronous resources."""

        ...
