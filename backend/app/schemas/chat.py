"""Public, stateless HTTP contracts for Chat API completions."""

from datetime import datetime, timezone
from enum import StrEnum
from typing import Annotated, Literal, Self

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    field_validator,
    model_validator,
)


RequestId = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        min_length=1,
        max_length=128,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]*$",
    ),
]
ModelName = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=255),
]
ProviderName = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=64),
]
ErrorCode = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        min_length=1,
        max_length=64,
        pattern=r"^[a-z][a-z0-9_]*$",
    ),
]


class _ChatSchema(BaseModel):
    """Apply strict, immutable semantics to every public Chat contract."""

    model_config = ConfigDict(extra="forbid", frozen=True)


class _TimestampedChatSchema(_ChatSchema):
    """Require and normalize one server-produced UTC timestamp."""

    created_at: AwareDatetime

    @field_validator("created_at")
    @classmethod
    def normalize_created_at(cls, value: datetime) -> datetime:
        """Represent response and event timestamps consistently in UTC."""

        return value.astimezone(timezone.utc)


class ChatMessageRole(StrEnum):
    """Client-controlled roles allowed by the stateless Chat API."""

    USER = "user"
    ASSISTANT = "assistant"


class ChatFinishReason(StrEnum):
    """Public reasons why a Chat completion stopped producing output."""

    STOP = "stop"
    LENGTH = "length"
    CONTENT_FILTER = "content_filter"
    CANCELLED = "cancelled"
    UNKNOWN = "unknown"


class ChatMessage(_ChatSchema):
    """Represent one client-supplied message in the current request context."""

    role: ChatMessageRole
    content: str = Field(min_length=1)

    @field_validator("content")
    @classmethod
    def validate_content(cls, value: str) -> str:
        """Reject blank content while preserving meaningful whitespace."""

        if not value.strip():
            raise ValueError("Message content must not be blank")
        return value


class ChatRequest(_ChatSchema):
    """Describe one stateless Chat completion request."""

    messages: tuple[ChatMessage, ...] = Field(min_length=1)
    model_name: ModelName | None = None
    temperature: float | None = Field(
        default=None,
        ge=0.0,
        le=2.0,
        allow_inf_nan=False,
        strict=True,
    )
    max_tokens: int | None = Field(default=None, ge=1, strict=True)
    stream: bool = Field(default=False, strict=True)
    request_id: RequestId | None = None

    @model_validator(mode="after")
    def validate_message_context(self) -> Self:
        """Require a user-authored request without enforcing role alternation."""

        if not any(message.role is ChatMessageRole.USER for message in self.messages):
            raise ValueError("At least one user message is required")
        if self.messages[-1].role is not ChatMessageRole.USER:
            raise ValueError("The final message must have the user role")
        return self


class ChatUsage(_ChatSchema):
    """Expose normalized token counts when the model reports them."""

    input_tokens: int | None = Field(default=None, ge=0, strict=True)
    output_tokens: int | None = Field(default=None, ge=0, strict=True)
    total_tokens: int | None = Field(default=None, ge=0, strict=True)


class ChatResponse(_TimestampedChatSchema):
    """Return one complete Chat result without exposing an LLM SDK object."""

    answer: str
    provider_name: ProviderName
    model_name: ModelName
    finish_reason: ChatFinishReason
    usage: ChatUsage | None = None
    request_id: RequestId


class ChatStreamChunkEvent(_TimestampedChatSchema):
    """Carry one ordered text delta in a future SSE response."""

    event: Literal["chunk"] = "chunk"
    request_id: RequestId
    sequence: int = Field(ge=0, strict=True)
    delta: str
    provider_name: ProviderName
    model_name: ModelName


class ChatStreamDoneEvent(_TimestampedChatSchema):
    """Mark successful completion of a future SSE response."""

    event: Literal["done"] = "done"
    request_id: RequestId
    sequence: int = Field(ge=0, strict=True)
    provider_name: ProviderName
    model_name: ModelName
    finish_reason: ChatFinishReason
    usage: ChatUsage | None = None


class ChatStreamErrorEvent(_TimestampedChatSchema):
    """Report a sanitized failure after a future SSE response has started."""

    event: Literal["error"] = "error"
    request_id: RequestId
    code: ErrorCode
    message: str = Field(min_length=1)
    retry_after_seconds: float | None = Field(
        default=None,
        ge=0,
        allow_inf_nan=False,
    )


type ChatStreamEvent = Annotated[
    ChatStreamChunkEvent | ChatStreamDoneEvent | ChatStreamErrorEvent,
    Field(discriminator="event"),
]


__all__ = (
    "ChatFinishReason",
    "ChatMessage",
    "ChatMessageRole",
    "ChatRequest",
    "ChatResponse",
    "ChatStreamChunkEvent",
    "ChatStreamDoneEvent",
    "ChatStreamErrorEvent",
    "ChatStreamEvent",
    "ChatUsage",
)
