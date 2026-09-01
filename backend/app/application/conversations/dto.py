"""Immutable application DTOs for conversation use cases."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from math import isfinite
from uuid import UUID

from app.domain.conversations import (
    Conversation,
    ConversationStatus,
    Message,
    MessageRole,
)


@dataclass(frozen=True, slots=True)
class CreateConversationCommand:
    title: str | None = None


@dataclass(frozen=True, slots=True)
class ArchiveConversationCommand:
    conversation_id: UUID


@dataclass(frozen=True, slots=True)
class ConversationChatCommand:
    conversation_id: UUID
    user_content: str = field(repr=False)
    request_id: str | None = None
    idempotency_key: str | None = None
    model_name: str | None = None
    temperature: float | None = None
    max_tokens: int | None = None
    context_limit: int = 20

    def __post_init__(self) -> None:
        if not isinstance(self.user_content, str) or not self.user_content.strip():
            raise ValueError("user_content must not be blank")
        if (
            isinstance(self.context_limit, bool)
            or not isinstance(self.context_limit, int)
            or self.context_limit <= 0
        ):
            raise ValueError("context_limit must be positive")
        if self.request_id is not None:
            self._validate_optional_text(
                self.request_id,
                field_name="request_id",
                max_length=128,
            )
        if self.idempotency_key is not None:
            self._validate_optional_text(
                self.idempotency_key,
                field_name="idempotency_key",
                max_length=255,
            )
        if (
            self.request_id is not None
            and self.idempotency_key is not None
            and self.request_id.strip() == self.idempotency_key.strip()
        ):
            raise ValueError("request_id and idempotency_key must be distinct")
        if self.model_name is not None:
            self._validate_optional_text(
                self.model_name,
                field_name="model_name",
                max_length=255,
            )
        if self.temperature is not None:
            if (
                isinstance(self.temperature, bool)
                or not isinstance(self.temperature, (int, float))
                or not isfinite(self.temperature)
                or not 0 <= self.temperature <= 2
            ):
                raise ValueError("temperature must be between 0 and 2")
        if (
            self.max_tokens is not None
            and (
                isinstance(self.max_tokens, bool)
                or not isinstance(self.max_tokens, int)
                or self.max_tokens <= 0
            )
        ):
            raise ValueError("max_tokens must be a positive integer")

    @staticmethod
    def _validate_optional_text(
        value: str,
        *,
        field_name: str,
        max_length: int,
    ) -> None:
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"{field_name} must not be blank")
        if len(value.strip()) > max_length:
            raise ValueError(f"{field_name} is too long")


@dataclass(frozen=True, slots=True)
class ConversationView:
    id: UUID
    title: str | None
    status: ConversationStatus
    created_at: datetime
    updated_at: datetime
    archived_at: datetime | None

    @classmethod
    def from_domain(cls, conversation: Conversation) -> ConversationView:
        return cls(
            id=conversation.id,
            title=conversation.title,
            status=conversation.status,
            created_at=conversation.created_at,
            updated_at=conversation.updated_at,
            archived_at=conversation.archived_at,
        )


@dataclass(frozen=True, slots=True)
class MessageView:
    id: UUID
    conversation_id: UUID
    turn_id: UUID
    role: MessageRole
    content: str = field(repr=False)
    sequence: int
    created_at: datetime

    @classmethod
    def from_domain(cls, message: Message) -> MessageView:
        return cls(
            id=message.id,
            conversation_id=message.conversation_id,
            turn_id=message.turn_id,
            role=message.role,
            content=message.content,
            sequence=message.sequence,
            created_at=message.created_at,
        )


@dataclass(frozen=True, slots=True)
class ConversationPage:
    items: tuple[ConversationView, ...]
    offset: int
    limit: int


@dataclass(frozen=True, slots=True)
class MessagePage:
    items: tuple[MessageView, ...]
    after_sequence: int | None
    limit: int
    next_sequence: int | None


@dataclass(frozen=True, slots=True)
class TokenUsageView:
    input_tokens: int | None
    output_tokens: int | None
    total_tokens: int | None


@dataclass(frozen=True, slots=True)
class ConversationChatResult:
    conversation_id: UUID
    turn_id: UUID
    request_id: str
    answer: str = field(repr=False)
    provider_name: str
    model_name: str
    finish_reason: str
    usage: TokenUsageView
    completed_at: datetime
