"""Vendor-neutral exception boundary for the LLM provider layer."""

from typing import ClassVar


class LLMException(Exception):
    """Base exception exposed by the vendor-neutral LLM boundary."""

    code: ClassVar[str] = "llm_error"
    retryable: ClassVar[bool] = False

    def __init__(
        self,
        message: str,
        *,
        provider_name: str | None = None,
        provider_request_id: str | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.provider_name = provider_name
        self.provider_request_id = provider_request_id


class ProviderTimeout(LLMException):
    """Raised when a provider operation exceeds its allowed duration."""

    code = "provider_timeout"
    retryable = True


class ProviderAuthenticationError(LLMException):
    """Raised when a provider rejects configured credentials."""

    code = "provider_authentication_error"


class ProviderRateLimitError(LLMException):
    """Raised when a provider temporarily rejects work due to a usage limit."""

    code = "provider_rate_limit_error"
    retryable = True

    def __init__(
        self,
        message: str,
        *,
        provider_name: str | None = None,
        provider_request_id: str | None = None,
        retry_after_seconds: float | None = None,
    ) -> None:
        if retry_after_seconds is not None and retry_after_seconds < 0:
            raise ValueError("retry_after_seconds must be greater than or equal to zero")

        super().__init__(
            message,
            provider_name=provider_name,
            provider_request_id=provider_request_id,
        )
        self.retry_after_seconds = retry_after_seconds


class ProviderUnavailable(LLMException):
    """Raised when a provider cannot currently serve requests."""

    code = "provider_unavailable"
    retryable = True


class ProviderConfigurationError(LLMException):
    """Raised when provider configuration is missing or invalid."""

    code = "provider_configuration_error"


class ProviderNotRegistered(LLMException):
    """Raised when a requested provider has no registered implementation."""

    code = "provider_not_registered"


class ProviderInvalidResponse(LLMException):
    """Raised when a provider response cannot satisfy the public contract."""

    code = "provider_invalid_response"


__all__ = (
    "LLMException",
    "ProviderAuthenticationError",
    "ProviderConfigurationError",
    "ProviderInvalidResponse",
    "ProviderNotRegistered",
    "ProviderRateLimitError",
    "ProviderTimeout",
    "ProviderUnavailable",
)
