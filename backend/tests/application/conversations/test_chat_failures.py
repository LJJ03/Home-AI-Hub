"""Failure and cancellation tests for persistent conversation chat."""

import asyncio
from datetime import UTC, datetime, timedelta

import pytest

from app.application.conversations import (
    ConversationChatCommand,
    ConversationChatService,
    ConversationGenerationError,
)
from app.domain.conversations import Conversation, TurnStatus
from app.llm.exceptions import ProviderTimeout
from app.llm.schemas import LLMRequest, LLMResponse
from tests.application.conversations.fakes import (
    CancellingLLMService,
    FakeLLMService,
    FakeUnitOfWorkFactory,
)


NOW = datetime(2026, 9, 1, 13, 0, tzinfo=UTC)


@pytest.mark.asyncio
async def test_llm_failure_is_sanitized_persisted_and_never_retried() -> None:
    conversation = Conversation.create(created_at=NOW)
    factory = FakeUnitOfWorkFactory()
    factory.store.seed(conversation)
    llm = FakeLLMService(
        factory,
        error=ProviderTimeout(
            "raw provider body with sensitive data",
            provider_name="mock",
            provider_request_id="provider-secret-id",
        ),
    )
    service = ConversationChatService(
        unit_of_work_factory=factory,
        llm_service=llm,
        clock=lambda: NOW + timedelta(seconds=1),
    )

    with pytest.raises(ConversationGenerationError) as captured:
        await service.complete(
            ConversationChatCommand(
                conversation_id=conversation.id,
                user_content="private prompt",
                request_id="request-7",
            )
        )

    assert captured.value.code == "provider_timeout"
    assert "sensitive" not in str(captured.value)
    assert "provider-secret-id" not in str(captured.value)
    assert len(llm.requests) == 1
    assert factory.store.events.count("llm.generate") == 1
    turn = next(iter(factory.store.turns.values()))
    assert turn.status is TurnStatus.FAILED
    assert turn.safe_error_code == "provider_timeout"
    assert turn.assistant_message is None
    assert "raw provider body" not in repr(turn)
    assert "private prompt" not in repr(turn.user_message)


@pytest.mark.asyncio
async def test_cancelled_error_propagates_after_best_effort_cancel_state() -> None:
    conversation = Conversation.create(created_at=NOW)
    factory = FakeUnitOfWorkFactory()
    factory.store.seed(conversation)
    llm = CancellingLLMService(factory)
    service = ConversationChatService(
        unit_of_work_factory=factory,
        llm_service=llm,
        clock=lambda: NOW + timedelta(seconds=1),
    )

    with pytest.raises(asyncio.CancelledError):
        await service.complete(
            ConversationChatCommand(
                conversation_id=conversation.id,
                user_content="cancel me",
                request_id="request-8",
            )
        )

    turn = next(iter(factory.store.turns.values()))
    assert turn.status is TurnStatus.CANCELLED
    assert turn.assistant_message is None
    assert len(llm.requests) == 1


@pytest.mark.asyncio
async def test_task_cancellation_closes_llm_wait_and_persists_cancelled_state() -> None:
    conversation = Conversation.create(created_at=NOW)
    factory = FakeUnitOfWorkFactory()
    factory.store.seed(conversation)
    started = asyncio.Event()
    never_complete = asyncio.Event()

    class BlockingLLMService:
        async def generate(self, request: LLMRequest) -> LLMResponse:
            assert factory.store.active_transactions == 0
            factory.store.events.append("llm.generate")
            started.set()
            await never_complete.wait()
            raise AssertionError("unreachable")

    service = ConversationChatService(
        unit_of_work_factory=factory,
        llm_service=BlockingLLMService(),
        clock=lambda: NOW + timedelta(seconds=1),
    )
    task = asyncio.create_task(
        service.complete(
            ConversationChatCommand(
                conversation_id=conversation.id,
                user_content="cancel running task",
                request_id="request-10",
            )
        )
    )
    await started.wait()

    task.cancel()

    with pytest.raises(asyncio.CancelledError):
        await task
    turn = next(iter(factory.store.turns.values()))
    assert turn.status is TurnStatus.CANCELLED
    assert factory.store.active_transactions == 0
