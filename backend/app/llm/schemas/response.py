"""Vendor-neutral response contracts for LLM text generation."""

from enum import StrEnum
from typing import Annotated, Self

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator


ProviderName = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=64),
]
ModelName = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=255),
]
ProviderRequestId = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=512),
]


class FinishReason(StrEnum):
    """Normalized reasons why a provider stopped generating text."""

    STOP = "stop"
    LENGTH = "length"
    CONTENT_FILTER = "content_filter"
    CANCELLED = "cancelled"
    UNKNOWN = "unknown"


class TokenUsage(BaseModel):
    """Represent provider-reported token counts when they are available."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    input_tokens: int | None = Field(default=None, ge=0, strict=True)
    output_tokens: int | None = Field(default=None, ge=0, strict=True)
    total_tokens: int | None = Field(default=None, ge=0, strict=True)


class LLMResponse(BaseModel):
    """Represent one complete normalized generation result."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    text: str
    provider_name: ProviderName
    model_name: ModelName
    finish_reason: FinishReason
    usage: TokenUsage | None = None
    provider_request_id: ProviderRequestId | None = None


class LLMStreamChunk(BaseModel):
    """Represent one ordered normalized chunk from a streaming generation."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    sequence: int = Field(ge=0, strict=True)
    delta: str = ""
    provider_name: ProviderName
    model_name: ModelName
    is_final: bool = False
    finish_reason: FinishReason | None = None
    usage: TokenUsage | None = None
    provider_request_id: ProviderRequestId | None = None

    @model_validator(mode="after")
    def validate_final_chunk(self) -> Self:
        """Keep completion metadata exclusive to the final stream chunk."""

        if self.is_final and self.finish_reason is None:
            raise ValueError("A final stream chunk requires a finish reason")
        if not self.is_final and (
            self.finish_reason is not None or self.usage is not None
        ):
            raise ValueError(
                "A non-final stream chunk cannot contain completion metadata"
            )
        return self
