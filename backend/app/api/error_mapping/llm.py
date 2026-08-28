"""Map vendor-neutral LLM failures to safe application HTTP errors."""

from dataclasses import dataclass
from math import isfinite

from fastapi import status

from app.core.exceptions import ApplicationError
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


@dataclass(frozen=True, slots=True)
class _LLMHTTPErrorSpec:
    """Describe one stable, client-safe HTTP representation."""

    status_code: int
    code: str
    message: str


_LLM_ERROR_SPECS: tuple[
    tuple[type[LLMException], _LLMHTTPErrorSpec], ...
] = (
    (
        ProviderConfigurationError,
        _LLMHTTPErrorSpec(
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            "llm_configuration_error",
            "LLM provider configuration is invalid",
        ),
    ),
    (
        ProviderNotRegistered,
        _LLMHTTPErrorSpec(
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            "llm_provider_not_registered",
            "Configured LLM provider is not registered",
        ),
    ),
    (
        ProviderAuthenticationError,
        _LLMHTTPErrorSpec(
            status.HTTP_502_BAD_GATEWAY,
            "llm_provider_authentication_failed",
            "LLM provider authentication failed",
        ),
    ),
    (
        ProviderRateLimitError,
        _LLMHTTPErrorSpec(
            status.HTTP_429_TOO_MANY_REQUESTS,
            "llm_rate_limited",
            "LLM request was rate limited",
        ),
    ),
    (
        ProviderTimeout,
        _LLMHTTPErrorSpec(
            status.HTTP_504_GATEWAY_TIMEOUT,
            "llm_provider_timeout",
            "LLM provider timed out",
        ),
    ),
    (
        ProviderUnavailable,
        _LLMHTTPErrorSpec(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "llm_provider_unavailable",
            "LLM provider is unavailable",
        ),
    ),
    (
        ProviderInvalidResponse,
        _LLMHTTPErrorSpec(
            status.HTTP_502_BAD_GATEWAY,
            "llm_invalid_response",
            "LLM provider returned an invalid response",
        ),
    ),
)
_DEFAULT_LLM_ERROR_SPEC = _LLMHTTPErrorSpec(
    status.HTTP_502_BAD_GATEWAY,
    "llm_provider_error",
    "LLM provider request failed",
)


def map_llm_exception(
    exception: LLMException,
    *,
    request_id: str | None,
) -> ApplicationError:
    """Convert an expected LLM failure without exposing provider diagnostics."""

    specification = next(
        (
            candidate
            for exception_type, candidate in _LLM_ERROR_SPECS
            if isinstance(exception, exception_type)
        ),
        _DEFAULT_LLM_ERROR_SPEC,
    )
    details: dict[str, str | float] = {}
    if request_id is not None:
        details["request_id"] = request_id
    if isinstance(exception, ProviderRateLimitError):
        retry_after_seconds = exception.retry_after_seconds
        if retry_after_seconds is not None and isfinite(retry_after_seconds):
            details["retry_after_seconds"] = retry_after_seconds

    return ApplicationError(
        status_code=specification.status_code,
        code=specification.code,
        message=specification.message,
        details=details or None,
    )


__all__ = ("map_llm_exception",)
