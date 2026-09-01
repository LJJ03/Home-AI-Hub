"""Bounded conversion from completed conversation history to an LLM request."""

from __future__ import annotations

from collections.abc import Sequence

from app.domain.conversations import Message, MessageRole
from app.llm.schemas import (
    LLMMessage,
    LLMRequest,
    MessageRole as LLMMessageRole,
)


class ConversationContextBuilder:
    """Build protocol DTOs without provider, persistence, or transport knowledge."""

    def __init__(
        self,
        *,
        max_messages: int = 20,
        max_characters: int = 32_000,
    ) -> None:
        if max_messages <= 0:
            raise ValueError("max_messages must be positive")
        if max_characters <= 0:
            raise ValueError("max_characters must be positive")
        self._max_messages = max_messages
        self._max_characters = max_characters

    def bounded_limit(self, requested_limit: int) -> int:
        """Clamp repository history reads to the configured finite maximum."""

        if requested_limit <= 0:
            raise ValueError("context_limit must be positive")
        return min(requested_limit, self._max_messages)

    def build(
        self,
        *,
        completed_history: Sequence[Message],
        current_user_message: Message,
        correlation_id: str,
        context_limit: int,
        model_name: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> LLMRequest:
        if context_limit <= 0:
            raise ValueError("context_limit must be positive")
        if current_user_message.role is not MessageRole.USER:
            raise ValueError("current_user_message must have the user role")

        effective_limit = self.bounded_limit(context_limit)
        ordered = sorted(completed_history, key=lambda message: message.sequence)
        candidates = ordered[-effective_limit:]

        remaining = self._max_characters - len(current_user_message.content)
        if remaining < 0:
            raise ValueError("current user message exceeds the context budget")

        selected_reversed: list[Message] = []
        for message in reversed(candidates):
            if message.role not in (MessageRole.USER, MessageRole.ASSISTANT):
                raise ValueError("unsupported message role in conversation history")
            if len(message.content) > remaining:
                break
            selected_reversed.append(message)
            remaining -= len(message.content)

        selected = tuple(reversed(selected_reversed))
        messages = tuple(self._to_llm_message(message) for message in selected) + (
            self._to_llm_message(current_user_message),
        )
        return LLMRequest(
            messages=messages,
            model_name=model_name,
            temperature=temperature,
            max_tokens=max_tokens,
            correlation_id=correlation_id,
        )

    @staticmethod
    def _to_llm_message(message: Message) -> LLMMessage:
        role = (
            LLMMessageRole.USER
            if message.role is MessageRole.USER
            else LLMMessageRole.ASSISTANT
        )
        return LLMMessage(role=role, content=message.content)
