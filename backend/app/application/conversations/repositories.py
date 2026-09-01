"""SQLAlchemy-free repository protocols for the conversation application."""

from collections.abc import Sequence
from typing import Protocol, runtime_checkable
from uuid import UUID

from app.domain.conversations import Conversation, ConversationTurn, Message


@runtime_checkable
class ConversationRepository(Protocol):
    """Persist and retrieve conversation aggregate roots without committing."""

    async def add(self, conversation: Conversation) -> None: ...

    async def get_by_id(self, conversation_id: UUID) -> Conversation | None: ...

    async def list(
        self,
        *,
        offset: int = 0,
        limit: int = 50,
    ) -> Sequence[Conversation]: ...

    async def save(self, conversation: Conversation) -> None: ...

    async def get_for_update(
        self,
        conversation_id: UUID,
    ) -> Conversation | None: ...


@runtime_checkable
class ConversationTurnRepository(Protocol):
    """Persist normalized turn state without owning the transaction."""

    async def add(self, turn: ConversationTurn) -> None: ...

    async def get_by_id(self, turn_id: UUID) -> ConversationTurn | None: ...

    async def get_by_idempotency_key(
        self,
        conversation_id: UUID,
        idempotency_key: str,
    ) -> ConversationTurn | None: ...

    async def list_pending(
        self,
        conversation_id: UUID,
        *,
        limit: int = 100,
    ) -> Sequence[ConversationTurn]: ...

    async def save(self, turn: ConversationTurn) -> None: ...


@runtime_checkable
class MessageRepository(Protocol):
    """Persist and read ordered final messages without committing."""

    async def add(self, message: Message) -> None: ...

    async def list_by_conversation(
        self,
        conversation_id: UUID,
        *,
        after_sequence: int | None = None,
        limit: int = 100,
    ) -> Sequence[Message]: ...

    async def list_recent_completed_for_context(
        self,
        conversation_id: UUID,
        *,
        limit: int = 20,
    ) -> Sequence[Message]: ...

    async def next_sequence(self, conversation_id: UUID) -> int | None: ...
