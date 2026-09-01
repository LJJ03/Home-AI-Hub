"""Safe, infrastructure-neutral conversation domain errors."""


class ConversationDomainError(Exception):
    """Base class for expected conversation invariant failures."""

    code = "conversation_domain_error"


class InvalidDomainValueError(ConversationDomainError):
    """Raised when a value cannot participate in the domain model."""

    code = "invalid_conversation_domain_value"


class ConversationArchivedError(ConversationDomainError):
    """Raised when an archived conversation receives a new write."""

    code = "conversation_archived"


class TurnNotFoundError(ConversationDomainError):
    """Raised when a requested turn is not part of the aggregate."""

    code = "conversation_turn_not_found"


class InvalidTurnTransitionError(ConversationDomainError):
    """Raised when a turn attempts an unsupported state transition."""

    code = "invalid_turn_transition"


class MessageContentError(ConversationDomainError):
    """Raised when message content is empty or blank."""

    code = "invalid_message_content"


class InvalidMessageRoleError(ConversationDomainError):
    """Raised when a message role is outside the public domain contract."""

    code = "invalid_message_role"


class MessageOwnershipError(ConversationDomainError):
    """Raised when a message belongs to another conversation or turn."""

    code = "invalid_message_ownership"


class MessageSequenceError(ConversationDomainError):
    """Raised when message ordering would stop being monotonic."""

    code = "invalid_message_sequence"


class TurnMessageConflictError(ConversationDomainError):
    """Raised when a turn would contain an invalid message cardinality."""

    code = "turn_message_conflict"


class IdempotencyConflictError(ConversationDomainError):
    """Raised when an idempotency key already belongs to another turn."""

    code = "idempotency_conflict"

