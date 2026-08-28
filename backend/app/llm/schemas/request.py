"""Vendor-neutral request contracts for LLM text generation."""

from enum import StrEnum
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator


ModelName = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=255),
]
CorrelationId = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=128),
]


class MessageRole(StrEnum):
    """Supported roles for one vendor-neutral model input message."""

    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"


class LLMMessage(BaseModel):
    """Represent one text-only message in the current generation request."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    role: MessageRole
    content: str = Field(min_length=1)

    @field_validator("content")
    @classmethod
    def validate_content(cls, value: str) -> str:
        """Reject empty text without altering meaningful whitespace."""

        if not value.strip():
            raise ValueError("Message content must not be blank")
        return value


class LLMRequest(BaseModel):
    """Describe one generation call without carrying conversation state."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    messages: tuple[LLMMessage, ...] = Field(min_length=1)
    model_name: ModelName | None = None
    temperature: float | None = Field(
        default=None,
        ge=0.0,
        le=2.0,
        allow_inf_nan=False,
    )
    max_tokens: int | None = Field(default=None, ge=1, strict=True)
    correlation_id: CorrelationId | None = None
