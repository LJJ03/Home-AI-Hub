"""Safe application errors for conversation use cases."""

from __future__ import annotations

from uuid import UUID


class ConversationApplicationError(Exception):
    """Base error whose message and code are safe at application boundaries."""

    code = "conversation_application_error"

    def __init__(self, message: str, *, code: str | None = None) -> None:
        super().__init__(message)
        if code is not None:
            self.code = code


class ConversationNotFoundError(ConversationApplicationError):
    code = "conversation_not_found"

    def __init__(self, conversation_id: UUID) -> None:
        super().__init__(
            f"Conversation {conversation_id} was not found",
            code=self.code,
        )


class ConversationConflictError(ConversationApplicationError):
    """Represent an expected write conflict without leaking domain internals."""

    def __init__(
        self,
        *,
        code: str = "conversation_conflict",
        message: str = "Conversation state conflicts with this operation",
    ) -> None:
        super().__init__(message, code=code)


class ConversationPersistenceUnavailableError(ConversationApplicationError):
    """Represent a temporary persistence outage at the application boundary."""

    code = "conversation_persistence_unavailable"

    def __init__(self) -> None:
        super().__init__(
            "Conversation persistence is temporarily unavailable",
            code=self.code,
        )


class ConversationGenerationError(ConversationApplicationError):
    """Sanitized failure returned when model generation does not complete."""

    def __init__(self, *, code: str = "llm_generation_failed") -> None:
        super().__init__(
            "Conversation response generation failed",
            code=code,
        )
