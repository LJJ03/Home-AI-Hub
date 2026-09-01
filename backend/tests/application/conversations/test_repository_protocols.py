"""Offline tests for repository and unit-of-work protocols."""

from collections.abc import Sequence
from types import TracebackType
from typing import Self
from uuid import UUID

import pytest

from app.application.conversations import (
    ConversationRepository,
    ConversationTurnRepository,
    ConversationUnitOfWork,
    MessageRepository,
)
from app.domain.conversations import Conversation, ConversationTurn, Message


class FakeConversationRepository:
    def __init__(self) -> None:
        self.items: dict[UUID, Conversation] = {}

    async def add(self, conversation: Conversation) -> None:
        self.items[conversation.id] = conversation

    async def get_by_id(self, conversation_id: UUID) -> Conversation | None:
        return self.items.get(conversation_id)

    async def list(
        self,
        *,
        offset: int = 0,
        limit: int = 50,
    ) -> Sequence[Conversation]:
        return tuple(self.items.values())[offset : offset + limit]

    async def save(self, conversation: Conversation) -> None:
        self.items[conversation.id] = conversation

    async def get_for_update(
        self,
        conversation_id: UUID,
    ) -> Conversation | None:
        return await self.get_by_id(conversation_id)


class FakeConversationTurnRepository:
    def __init__(self) -> None:
        self.items: dict[UUID, ConversationTurn] = {}

    async def add(self, turn: ConversationTurn) -> None:
        self.items[turn.id] = turn

    async def get_by_id(self, turn_id: UUID) -> ConversationTurn | None:
        return self.items.get(turn_id)

    async def get_by_idempotency_key(
        self,
        conversation_id: UUID,
        idempotency_key: str,
    ) -> ConversationTurn | None:
        return next(
            (
                turn
                for turn in self.items.values()
                if turn.conversation_id == conversation_id
                and turn.idempotency_key == idempotency_key
            ),
            None,
        )

    async def list_pending(
        self,
        conversation_id: UUID,
        *,
        limit: int = 100,
    ) -> Sequence[ConversationTurn]:
        return tuple(
            turn
            for turn in self.items.values()
            if turn.conversation_id == conversation_id
        )[:limit]

    async def save(self, turn: ConversationTurn) -> None:
        self.items[turn.id] = turn


class FakeMessageRepository:
    def __init__(self) -> None:
        self.items: dict[UUID, Message] = {}
        self.next_sequences: dict[UUID, int] = {}

    async def add(self, message: Message) -> None:
        self.items[message.id] = message
        self.next_sequences[message.conversation_id] = message.sequence + 1

    async def list_by_conversation(
        self,
        conversation_id: UUID,
        *,
        after_sequence: int | None = None,
        limit: int = 100,
    ) -> Sequence[Message]:
        threshold = 0 if after_sequence is None else after_sequence
        matches = sorted(
            (
                message
                for message in self.items.values()
                if message.conversation_id == conversation_id
                and message.sequence > threshold
            ),
            key=lambda message: message.sequence,
        )
        return tuple(matches[:limit])

    async def list_recent_completed_for_context(
        self,
        conversation_id: UUID,
        *,
        limit: int = 20,
    ) -> Sequence[Message]:
        messages = await self.list_by_conversation(
            conversation_id,
            limit=100,
        )
        return tuple(messages[-limit:])

    async def next_sequence(self, conversation_id: UUID) -> int | None:
        return self.next_sequences.get(conversation_id)


class FakeConversationUnitOfWork:
    def __init__(self) -> None:
        self.conversation_repository = FakeConversationRepository()
        self.turn_repository = FakeConversationTurnRepository()
        self.message_repository = FakeMessageRepository()
        self.committed = False
        self.rolled_back = False

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        if exc_type is not None:
            await self.rollback()

    async def commit(self) -> None:
        self.committed = True

    async def rollback(self) -> None:
        self.rolled_back = True


def test_fake_adapters_satisfy_the_public_protocols() -> None:
    unit_of_work = FakeConversationUnitOfWork()

    assert isinstance(unit_of_work.conversation_repository, ConversationRepository)
    assert isinstance(unit_of_work.turn_repository, ConversationTurnRepository)
    assert isinstance(unit_of_work.message_repository, MessageRepository)
    assert isinstance(unit_of_work, ConversationUnitOfWork)


@pytest.mark.asyncio
async def test_fake_unit_of_work_owns_commit_and_rollback() -> None:
    committed = FakeConversationUnitOfWork()
    async with committed:
        await committed.commit()
    assert committed.committed
    assert not committed.rolled_back

    rolled_back = FakeConversationUnitOfWork()
    with pytest.raises(RuntimeError, match="expected failure"):
        async with rolled_back:
            raise RuntimeError("expected failure")
    assert rolled_back.rolled_back
