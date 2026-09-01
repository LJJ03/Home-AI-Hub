"""Public HTTP schemas for persistent conversation resources."""

from __future__ import annotations

from datetime import datetime, timezone
from enum import StrEnum
from typing import Annotated
from uuid import UUID

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    field_validator,
)

from app.application.conversations.dto import (
    ConversationChatResult,
    ConversationPage,
    ConversationView,
    MessagePage,
    MessageView,
)


ConversationTitle = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=200),
]
IdempotencyKey = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=255),
]
ProviderName = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=64),
]
ModelName = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=255),
]
RequestId = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=128),
]


class _ConversationSchema(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class _TimestampedSchema(_ConversationSchema):
    created_at: AwareDatetime

    @field_validator("created_at")
    @classmethod
    def normalize_created_at(cls, value: datetime) -> datetime:
        return value.astimezone(timezone.utc)


class ConversationStatusValue(StrEnum):
    ACTIVE = "active"
    ARCHIVED = "archived"


class ConversationTurnStatusValue(StrEnum):
    COMPLETED = "completed"


class MessageRoleValue(StrEnum):
    USER = "user"
    ASSISTANT = "assistant"


class FinishReasonValue(StrEnum):
    STOP = "stop"
    LENGTH = "length"
    CONTENT_FILTER = "content_filter"
    CANCELLED = "cancelled"
    UNKNOWN = "unknown"


class CreateConversationRequest(_ConversationSchema):
    title: ConversationTitle | None = None


class ConversationResponse(_ConversationSchema):
    id: UUID
    title: str | None
    status: ConversationStatusValue
    created_at: AwareDatetime
    updated_at: AwareDatetime
    archived_at: AwareDatetime | None

    @field_validator("created_at", "updated_at", "archived_at")
    @classmethod
    def normalize_timestamps(cls, value: datetime | None) -> datetime | None:
        return None if value is None else value.astimezone(timezone.utc)

    @classmethod
    def from_application(cls, view: ConversationView) -> ConversationResponse:
        return cls(
            id=view.id,
            title=view.title,
            status=ConversationStatusValue(view.status.value),
            created_at=view.created_at,
            updated_at=view.updated_at,
            archived_at=view.archived_at,
        )


class ConversationListResponse(_ConversationSchema):
    items: tuple[ConversationResponse, ...]
    offset: int = Field(ge=0, strict=True)
    limit: int = Field(ge=1, le=100, strict=True)
    next_offset: int | None = Field(default=None, ge=0, strict=True)

    @classmethod
    def from_application(cls, page: ConversationPage) -> ConversationListResponse:
        items = tuple(
            ConversationResponse.from_application(item) for item in page.items
        )
        return cls(
            items=items,
            offset=page.offset,
            limit=page.limit,
            next_offset=(
                page.offset + len(items) if len(items) == page.limit else None
            ),
        )


class MessageResponse(_TimestampedSchema):
    id: UUID
    conversation_id: UUID
    turn_id: UUID
    role: MessageRoleValue
    content: str = Field(min_length=1)
    sequence: int = Field(ge=1, strict=True)

    @classmethod
    def from_application(cls, view: MessageView) -> MessageResponse:
        return cls(
            id=view.id,
            conversation_id=view.conversation_id,
            turn_id=view.turn_id,
            role=MessageRoleValue(view.role.value),
            content=view.content,
            sequence=view.sequence,
            created_at=view.created_at,
        )


class MessageListResponse(_ConversationSchema):
    items: tuple[MessageResponse, ...]
    after_sequence: int | None = Field(default=None, ge=1, strict=True)
    limit: int = Field(ge=1, le=100, strict=True)
    next_cursor: int | None = Field(default=None, ge=1, strict=True)

    @classmethod
    def from_application(cls, page: MessagePage) -> MessageListResponse:
        return cls(
            items=tuple(MessageResponse.from_application(item) for item in page.items),
            after_sequence=page.after_sequence,
            limit=page.limit,
            next_cursor=page.next_sequence,
        )


class CreateTurnRequest(_ConversationSchema):
    content: str = Field(min_length=1, max_length=32_000)
    idempotency_key: IdempotencyKey | None = None

    @field_validator("content")
    @classmethod
    def validate_content(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Message content must not be blank")
        return value


class ConversationUsageResponse(_ConversationSchema):
    input_tokens: int | None = Field(default=None, ge=0, strict=True)
    output_tokens: int | None = Field(default=None, ge=0, strict=True)
    total_tokens: int | None = Field(default=None, ge=0, strict=True)


class CreateTurnResponse(_ConversationSchema):
    conversation_id: UUID
    turn_id: UUID
    user_message: MessageResponse
    assistant_message: MessageResponse
    provider_name: ProviderName
    model_name: ModelName
    finish_reason: FinishReasonValue
    usage: ConversationUsageResponse
    request_id: RequestId
    status: ConversationTurnStatusValue

    @classmethod
    def from_application(cls, result: ConversationChatResult) -> CreateTurnResponse:
        return cls(
            conversation_id=result.conversation_id,
            turn_id=result.turn_id,
            user_message=MessageResponse.from_application(result.user_message),
            assistant_message=MessageResponse.from_application(
                result.assistant_message
            ),
            provider_name=result.provider_name,
            model_name=result.model_name,
            finish_reason=FinishReasonValue(result.finish_reason),
            usage=ConversationUsageResponse(
                input_tokens=result.usage.input_tokens,
                output_tokens=result.usage.output_tokens,
                total_tokens=result.usage.total_tokens,
            ),
            request_id=result.request_id,
            status=ConversationTurnStatusValue(result.status.value),
        )


class ArchiveConversationResponse(_ConversationSchema):
    conversation: ConversationResponse
    status: ConversationStatusValue

    @classmethod
    def from_application(
        cls,
        view: ConversationView,
    ) -> ArchiveConversationResponse:
        conversation = ConversationResponse.from_application(view)
        return cls(conversation=conversation, status=conversation.status)


__all__ = (
    "ArchiveConversationResponse",
    "ConversationListResponse",
    "ConversationResponse",
    "ConversationUsageResponse",
    "CreateConversationRequest",
    "CreateTurnRequest",
    "CreateTurnResponse",
    "MessageListResponse",
    "MessageResponse",
)
