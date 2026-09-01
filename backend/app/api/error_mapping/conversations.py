"""Map safe conversation application failures to stable HTTP errors."""

from dataclasses import dataclass

from fastapi import status

from app.application.conversations import (
    ConversationApplicationError,
    ConversationConflictError,
    ConversationGenerationError,
    ConversationNotFoundError,
    ConversationPersistenceUnavailableError,
)
from app.core.exceptions import ApplicationError


@dataclass(frozen=True, slots=True)
class _HTTPErrorSpec:
    status_code: int
    code: str
    message: str


_GENERATION_ERROR_SPECS: dict[str, _HTTPErrorSpec] = {
    "provider_configuration_error": _HTTPErrorSpec(
        status.HTTP_500_INTERNAL_SERVER_ERROR,
        "llm_configuration_error",
        "LLM provider configuration is invalid",
    ),
    "provider_not_registered": _HTTPErrorSpec(
        status.HTTP_500_INTERNAL_SERVER_ERROR,
        "llm_provider_not_registered",
        "Configured LLM provider is not registered",
    ),
    "provider_authentication_error": _HTTPErrorSpec(
        status.HTTP_502_BAD_GATEWAY,
        "llm_provider_authentication_failed",
        "LLM provider authentication failed",
    ),
    "provider_rate_limit_error": _HTTPErrorSpec(
        status.HTTP_429_TOO_MANY_REQUESTS,
        "llm_rate_limited",
        "LLM request was rate limited",
    ),
    "provider_timeout": _HTTPErrorSpec(
        status.HTTP_504_GATEWAY_TIMEOUT,
        "llm_provider_timeout",
        "LLM provider timed out",
    ),
    "provider_unavailable": _HTTPErrorSpec(
        status.HTTP_503_SERVICE_UNAVAILABLE,
        "llm_provider_unavailable",
        "LLM provider is unavailable",
    ),
    "provider_invalid_response": _HTTPErrorSpec(
        status.HTTP_502_BAD_GATEWAY,
        "llm_invalid_response",
        "LLM provider returned an invalid response",
    ),
}
_DEFAULT_GENERATION_ERROR = _HTTPErrorSpec(
    status.HTTP_502_BAD_GATEWAY,
    "llm_provider_error",
    "LLM provider request failed",
)


def map_conversation_exception(
    exception: ConversationApplicationError,
) -> ApplicationError:
    """Return an allowlisted representation without copying exception text."""

    if isinstance(exception, ConversationNotFoundError):
        return ApplicationError(
            status_code=status.HTTP_404_NOT_FOUND,
            code="conversation_not_found",
            message="Conversation was not found",
        )
    if isinstance(exception, ConversationConflictError):
        code = (
            exception.code
            if exception.code
            in {"conversation_archived", "idempotency_conflict"}
            else "conversation_conflict"
        )
        message = {
            "conversation_archived": "Conversation is archived",
            "idempotency_conflict": "The idempotency key is already in use",
            "conversation_conflict": "Conversation state conflicts with this operation",
        }[code]
        return ApplicationError(
            status_code=status.HTTP_409_CONFLICT,
            code=code,
            message=message,
        )
    if isinstance(exception, ConversationPersistenceUnavailableError):
        return ApplicationError(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            code="conversation_persistence_unavailable",
            message="Conversation persistence is temporarily unavailable",
        )
    if isinstance(exception, ConversationGenerationError):
        specification = _GENERATION_ERROR_SPECS.get(
            exception.code,
            _DEFAULT_GENERATION_ERROR,
        )
        return ApplicationError(
            status_code=specification.status_code,
            code=specification.code,
            message=specification.message,
        )
    return ApplicationError(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        code="conversation_application_error",
        message="Conversation operation failed",
    )


__all__ = ("map_conversation_exception",)
