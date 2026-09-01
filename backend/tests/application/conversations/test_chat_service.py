"""Success-path orchestration tests for persistent conversation chat."""

from datetime import UTC, datetime, timedelta

import pytest

from app.application.conversations import (
    ConversationChatCommand,
    ConversationChatService,
)
from app.domain.conversations import Conversation, TurnStatus
from tests.application.conversations.fakes import (
    FakeLLMService,
    FakeUnitOfWorkFactory,
)


NOW = datetime(2026, 9, 1, 12, 0, tzinfo=UTC)


@pytest.mark.asyncio
async def test_chat_commits_pending_before_llm_and_result_in_second_transaction() -> None:
    conversation = Conversation.create(created_at=NOW)
    previous = conversation.start_turn(
        user_content="previous",
        created_at=NOW + timedelta(seconds=1),
    )
    conversation.complete_turn(
        previous.id,
        assistant_content="previous answer",
        completed_at=NOW + timedelta(seconds=2),
    )
    factory = FakeUnitOfWorkFactory()
    factory.store.seed(conversation)
    llm = FakeLLMService(factory)
    service = ConversationChatService(
        unit_of_work_factory=factory,
        llm_service=llm,
        clock=lambda: NOW + timedelta(seconds=3),
    )

    result = await service.complete(
        ConversationChatCommand(
            conversation_id=conversation.id,
            user_content="current secret input",
            request_id="request-5",
            idempotency_key="idempotency-5",
            context_limit=20,
        )
    )

    events = factory.store.events
    llm_index = events.index("llm.generate")
    commits_before_llm = [
        index
        for index, event in enumerate(events[:llm_index])
        if event == "uow.commit"
    ]
    assert commits_before_llm
    assert events[llm_index + 1] == "uow.enter"
    assert factory.store.active_transactions == 0
    assert len(llm.requests) == 1
    assert [message.content for message in llm.requests[0].messages] == [
        "previous",
        "previous answer",
        "current secret input",
    ]

    persisted_turn = factory.store.turns[result.turn_id]
    assert persisted_turn.status is TurnStatus.COMPLETED
    assert persisted_turn.provider_name == "mock"
    assert persisted_turn.model_name == "mock-default"
    assert persisted_turn.finish_reason == "stop"
    assert persisted_turn.usage is not None
    assert persisted_turn.usage.total_tokens == 5
    assert persisted_turn.assistant_message is not None
    assert persisted_turn.assistant_message.content == "offline answer"
    assert result.answer == "offline answer"
    assert "offline answer" not in repr(result)
    assert "current secret input" not in repr(
        ConversationChatCommand(
            conversation_id=conversation.id,
            user_content="current secret input",
        )
    )


@pytest.mark.asyncio
async def test_context_query_excludes_pending_or_failed_turn_messages() -> None:
    conversation = Conversation.create(created_at=NOW)
    failed = conversation.start_turn(
        user_content="failed historical input",
        created_at=NOW + timedelta(seconds=1),
    )
    conversation.fail_turn(
        failed.id,
        safe_error_code="safe_failure",
        completed_at=NOW + timedelta(seconds=2),
    )
    pending = conversation.start_turn(
        user_content="pending historical input",
        created_at=NOW + timedelta(seconds=3),
    )
    factory = FakeUnitOfWorkFactory()
    factory.store.seed(conversation)
    llm = FakeLLMService(factory)
    service = ConversationChatService(
        unit_of_work_factory=factory,
        llm_service=llm,
        clock=lambda: NOW + timedelta(seconds=4),
    )

    await service.complete(
        ConversationChatCommand(
            conversation_id=conversation.id,
            user_content="only current",
            request_id="request-6",
        )
    )

    contents = [message.content for message in llm.requests[0].messages]
    assert contents == ["only current"]
    assert failed.user_message.content not in contents
    assert pending.user_message.content not in contents


@pytest.mark.asyncio
async def test_chat_clamps_repository_history_read_to_builder_limit() -> None:
    conversation = Conversation.create(created_at=NOW)
    factory = FakeUnitOfWorkFactory()
    factory.store.seed(conversation)
    llm = FakeLLMService(factory)
    service = ConversationChatService(
        unit_of_work_factory=factory,
        llm_service=llm,
        clock=lambda: NOW + timedelta(seconds=1),
    )

    await service.complete(
        ConversationChatCommand(
            conversation_id=conversation.id,
            user_content="bounded",
            request_id="request-9",
            context_limit=10_000,
        )
    )

    assert factory.store.context_limits == [20]
