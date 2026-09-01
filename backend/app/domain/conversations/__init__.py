"""Public pure-Python contract for the conversation domain."""

from app.domain.conversations.entities import (
    Conversation,
    ConversationTurn,
    Message,
)
from app.domain.conversations.enums import (
    ConversationStatus,
    MessageRole,
    TurnStatus,
)
from app.domain.conversations.errors import (
    ConversationArchivedError,
    ConversationDomainError,
    IdempotencyConflictError,
    InvalidDomainValueError,
    InvalidMessageRoleError,
    InvalidTurnTransitionError,
    MessageContentError,
    MessageOwnershipError,
    MessageSequenceError,
    TurnMessageConflictError,
    TurnNotFoundError,
)
from app.domain.conversations.value_objects import TokenUsage


__all__ = (
    "Conversation",
    "ConversationArchivedError",
    "ConversationDomainError",
    "ConversationStatus",
    "ConversationTurn",
    "IdempotencyConflictError",
    "InvalidDomainValueError",
    "InvalidMessageRoleError",
    "InvalidTurnTransitionError",
    "Message",
    "MessageContentError",
    "MessageOwnershipError",
    "MessageRole",
    "MessageSequenceError",
    "TokenUsage",
    "TurnMessageConflictError",
    "TurnNotFoundError",
    "TurnStatus",
)
