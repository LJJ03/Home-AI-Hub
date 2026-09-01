"""In-memory test doubles for conversation application services."""

from __future__ import annotations

import asyncio
from copy import deepcopy
from dataclasses import dataclass, field
from types import TracebackType
from typing import Self
from uuid import UUID

from app.domain.conversations import (
    Conversation,
    ConversationTurn,
    Message,
    TurnStatus,
)
from app.llm.schemas import (
    FinishReason,
    LLMRequest,
    LLMResponse,
    TokenUsage,
)


@dataclass(slots=True)
class FakeStore:
    conversations: dict[UUID, Conversation] = field(default_factory=dict)
    turns: dict[UUID, ConversationTurn] = field(default_factory=dict)
    messages: dict[UUID, Message] = field(default_factory=dict)
    events: list[str] = field(default_factory=list)
    context_limits: list[int] = field(default_factory=list)
    active_transactions: int = 0

    def seed(self, conversation: Conversation) -> None:
        self.conversations[conversation.id] = deepcopy(conversation)
        for turn in conversation.turns:
            self.turns[turn.id] = deepcopy(turn)
        for message in conversation.messages:
            self.messages[message.id] = deepcopy(message)


class FakeConversationRepository:
    def __init__(self, items: dict[UUID, Conversation], events: list[str]) -> None:
        self._items = items
        self._events = events

    async def add(self, conversation: Conversation) -> None:
        self._events.append("conversation.add")
        self._items[conversation.id] = conversation

    async def get_by_id(self, conversation_id: UUID) -> Conversation | None:
        self._events.append("conversation.get")
        return self._items.get(conversation_id)

    async def list(
        self,
        *,
        offset: int = 0,
        limit: int = 50,
    ) -> tuple[Conversation, ...]:
        self._events.append("conversation.list")
        values = sorted(self._items.values(), key=lambda item: (item.created_at, item.id))
        return tuple(values[offset : offset + limit])

    async def save(self, conversation: Conversation) -> None:
        self._events.append("conversation.save")
        self._items[conversation.id] = conversation

    async def get_for_update(
        self,
        conversation_id: UUID,
    ) -> Conversation | None:
        self._events.append("conversation.lock")
        return self._items.get(conversation_id)


class FakeTurnRepository:
    def __init__(self, items: dict[UUID, ConversationTurn], events: list[str]) -> None:
        self._items = items
        self._events = events

    async def add(self, turn: ConversationTurn) -> None:
        self._events.append("turn.add")
        self._items[turn.id] = turn

    async def get_by_id(self, turn_id: UUID) -> ConversationTurn | None:
        self._events.append("turn.get")
        return self._items.get(turn_id)

    async def get_by_idempotency_key(
        self,
        conversation_id: UUID,
        idempotency_key: str,
    ) -> ConversationTurn | None:
        self._events.append("turn.get_by_idempotency_key")
        return next(
            (
                turn
                for turn in self._items.values()
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
    ) -> tuple[ConversationTurn, ...]:
        self._events.append("turn.list_pending")
        return tuple(
            turn
            for turn in sorted(self._items.values(), key=lambda item: item.sequence)
            if turn.conversation_id == conversation_id
            and turn.status is TurnStatus.PENDING
        )[:limit]

    async def save(self, turn: ConversationTurn) -> None:
        self._events.append("turn.save")
        self._items[turn.id] = turn


class FakeMessageRepository:
    def __init__(
        self,
        items: dict[UUID, Message],
        turns: dict[UUID, ConversationTurn],
        events: list[str],
        context_limits: list[int],
    ) -> None:
        self._items = items
        self._turns = turns
        self._events = events
        self._context_limits = context_limits

    async def add(self, message: Message) -> None:
        self._events.append("message.add")
        self._items[message.id] = message

    async def list_by_conversation(
        self,
        conversation_id: UUID,
        *,
        after_sequence: int | None = None,
        limit: int = 100,
    ) -> tuple[Message, ...]:
        self._events.append("message.list")
        return tuple(
            message
            for message in sorted(self._items.values(), key=lambda item: item.sequence)
            if message.conversation_id == conversation_id
            and (after_sequence is None or message.sequence > after_sequence)
        )[:limit]

    async def list_recent_completed_for_context(
        self,
        conversation_id: UUID,
        *,
        limit: int = 20,
    ) -> tuple[Message, ...]:
        self._events.append("message.list_completed_context")
        self._context_limits.append(limit)
        completed = [
            message
            for message in self._items.values()
            if message.conversation_id == conversation_id
            and self._turns[message.turn_id].status is TurnStatus.COMPLETED
        ]
        completed.sort(key=lambda item: item.sequence)
        return tuple(completed[-limit:])

    async def next_sequence(self, conversation_id: UUID) -> int | None:
        self._events.append("message.next_sequence")
        sequences = [
            message.sequence
            for message in self._items.values()
            if message.conversation_id == conversation_id
        ]
        return (max(sequences) + 1) if sequences else 1


class FakeUnitOfWork:
    def __init__(self, store: FakeStore) -> None:
        self._store = store
        self._committed = False
        self._conversations: dict[UUID, Conversation] = {}
        self._turns: dict[UUID, ConversationTurn] = {}
        self._messages: dict[UUID, Message] = {}
        self.conversation_repository: FakeConversationRepository
        self.turn_repository: FakeTurnRepository
        self.message_repository: FakeMessageRepository

    async def __aenter__(self) -> Self:
        self._store.events.append("uow.enter")
        self._store.active_transactions += 1
        self._conversations = deepcopy(self._store.conversations)
        self._turns = deepcopy(self._store.turns)
        self._messages = deepcopy(self._store.messages)
        self.conversation_repository = FakeConversationRepository(
            self._conversations,
            self._store.events,
        )
        self.turn_repository = FakeTurnRepository(self._turns, self._store.events)
        self.message_repository = FakeMessageRepository(
            self._messages,
            self._turns,
            self._store.events,
            self._store.context_limits,
        )
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        if exc_type is not None or not self._committed:
            await self.rollback()
        self._store.active_transactions -= 1
        self._store.events.append("uow.exit")

    async def commit(self) -> None:
        self._store.events.append("uow.commit")
        self._store.conversations = deepcopy(self._conversations)
        self._store.turns = deepcopy(self._turns)
        self._store.messages = deepcopy(self._messages)
        self._committed = True

    async def rollback(self) -> None:
        self._store.events.append("uow.rollback")


class FakeUnitOfWorkFactory:
    def __init__(self, store: FakeStore | None = None) -> None:
        self.store = store or FakeStore()

    def __call__(self) -> FakeUnitOfWork:
        return FakeUnitOfWork(self.store)


class FakeLLMService:
    def __init__(
        self,
        factory: FakeUnitOfWorkFactory,
        *,
        response: LLMResponse | None = None,
        error: BaseException | None = None,
    ) -> None:
        self._factory = factory
        self._response = response or LLMResponse(
            text="offline answer",
            provider_name="mock",
            model_name="mock-default",
            finish_reason=FinishReason.STOP,
            usage=TokenUsage(
                input_tokens=3,
                output_tokens=2,
                total_tokens=5,
            ),
        )
        self._error = error
        self.requests: list[LLMRequest] = []

    async def generate(self, request: LLMRequest) -> LLMResponse:
        assert self._factory.store.active_transactions == 0
        self._factory.store.events.append("llm.generate")
        self.requests.append(request)
        if self._error is not None:
            raise self._error
        return self._response


class CancellingLLMService(FakeLLMService):
    async def generate(self, request: LLMRequest) -> LLMResponse:
        assert self._factory.store.active_transactions == 0
        self._factory.store.events.append("llm.generate")
        self.requests.append(request)
        raise asyncio.CancelledError
