"""Transaction boundary protocol for conversation persistence."""

from types import TracebackType
from typing import Protocol, Self, runtime_checkable

from app.application.conversations.repositories import (
    ConversationRepository,
    ConversationTurnRepository,
    MessageRepository,
)


@runtime_checkable
class ConversationUnitOfWork(Protocol):
    """Expose one transaction without leaking its SQLAlchemy session."""

    @property
    def conversation_repository(self) -> ConversationRepository: ...

    @property
    def turn_repository(self) -> ConversationTurnRepository: ...

    @property
    def message_repository(self) -> MessageRepository: ...

    async def __aenter__(self) -> Self: ...

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None: ...

    async def commit(self) -> None: ...

    async def rollback(self) -> None: ...
