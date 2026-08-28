"""Vendor-neutral public contracts for the LLM provider layer."""

from app.llm.exceptions import (
    LLMException,
    ProviderAuthenticationError,
    ProviderConfigurationError,
    ProviderInvalidResponse,
    ProviderNotRegistered,
    ProviderRateLimitError,
    ProviderTimeout,
    ProviderUnavailable,
)
from app.llm.interfaces import LLMProvider
from app.llm.schemas import (
    FinishReason,
    LLMMessage,
    LLMRequest,
    LLMResponse,
    LLMStreamChunk,
    MessageRole,
    TokenUsage,
)


__all__ = (
    "FinishReason",
    "LLMException",
    "LLMMessage",
    "LLMProvider",
    "LLMRequest",
    "LLMResponse",
    "LLMStreamChunk",
    "MessageRole",
    "ProviderAuthenticationError",
    "ProviderConfigurationError",
    "ProviderInvalidResponse",
    "ProviderNotRegistered",
    "ProviderRateLimitError",
    "ProviderTimeout",
    "ProviderUnavailable",
    "TokenUsage",
)
