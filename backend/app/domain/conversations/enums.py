"""Stable enumerations for the conversation domain."""

from enum import StrEnum


class ConversationStatus(StrEnum):
    """Lifecycle states supported by a conversation aggregate."""

    ACTIVE = "active"
    ARCHIVED = "archived"


class TurnStatus(StrEnum):
    """Lifecycle states supported by one model-generation turn."""

    PENDING = "pending"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class MessageRole(StrEnum):
    """Roles persisted by the initial conversation domain."""

    USER = "user"
    ASSISTANT = "assistant"

