"""Application-facing ports used by conversation orchestration."""

from __future__ import annotations

from typing import Protocol

from app.llm.schemas import LLMRequest, LLMResponse


class ConversationLLMService(Protocol):
    """The only LLM capability required by the conversation application layer."""

    async def generate(self, request: LLMRequest) -> LLMResponse:
        """Generate one non-streaming response."""

        ...
