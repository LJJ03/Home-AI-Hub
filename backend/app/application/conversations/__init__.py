"""Public application boundaries and use cases for conversations."""

from app.application.conversations.context_builder import ConversationContextBuilder
from app.application.conversations.dto import (
    ArchiveConversationCommand,
    ConversationChatCommand,
    ConversationChatResult,
    ConversationPage,
    ConversationView,
    CreateConversationCommand,
    MessagePage,
    MessageView,
    TokenUsageView,
)
from app.application.conversations.errors import (
    ConversationApplicationError,
    ConversationGenerationError,
    ConversationNotFoundError,
)
from app.application.conversations.ports import ConversationLLMService
from app.application.conversations.repositories import (
    ConversationRepository,
    ConversationTurnRepository,
    MessageRepository,
)
from app.application.conversations.services import (
    ConversationChatService,
    ConversationCommandService,
    ConversationQueryService,
)
from app.application.conversations.unit_of_work import ConversationUnitOfWork


__all__ = (
    "ArchiveConversationCommand",
    "ConversationApplicationError",
    "ConversationChatCommand",
    "ConversationChatResult",
    "ConversationChatService",
    "ConversationCommandService",
    "ConversationContextBuilder",
    "ConversationGenerationError",
    "ConversationLLMService",
    "ConversationNotFoundError",
    "ConversationPage",
    "ConversationQueryService",
    "ConversationRepository",
    "ConversationTurnRepository",
    "ConversationUnitOfWork",
    "ConversationView",
    "CreateConversationCommand",
    "MessagePage",
    "MessageRepository",
    "MessageView",
    "TokenUsageView",
)
