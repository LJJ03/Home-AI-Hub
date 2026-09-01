"""Offline tests for bounded conversation context construction."""

from datetime import UTC, datetime, timedelta

import pytest

from app.application.conversations import ConversationContextBuilder
from app.domain.conversations import Conversation, MessageRole
from app.llm.schemas import MessageRole as LLMMessageRole


NOW = datetime(2026, 9, 1, 10, 0, tzinfo=UTC)


def _conversation_with_completed_turns(count: int) -> Conversation:
    conversation = Conversation.create(created_at=NOW)
    for index in range(count):
        turn = conversation.start_turn(
            user_content=f"user-{index}",
            created_at=NOW + timedelta(seconds=index * 2 + 1),
        )
        conversation.complete_turn(
            turn.id,
            assistant_content=f"assistant-{index}",
            completed_at=NOW + timedelta(seconds=index * 2 + 2),
        )
    return conversation


def test_context_is_ordered_bounded_and_contains_only_supported_roles() -> None:
    conversation = _conversation_with_completed_turns(3)
    current = conversation.start_turn(
        user_content="current input",
        created_at=NOW + timedelta(seconds=7),
    ).user_message
    builder = ConversationContextBuilder(max_messages=3, max_characters=1_000)

    request = builder.build(
        completed_history=conversation.messages[:-1],
        current_user_message=current,
        correlation_id="request-1",
        context_limit=10,
    )

    assert [message.content for message in request.messages] == [
        "assistant-1",
        "user-2",
        "assistant-2",
        "current input",
    ]
    assert all(
        message.role in (LLMMessageRole.USER, LLMMessageRole.ASSISTANT)
        for message in request.messages
    )


def test_context_character_budget_keeps_a_recent_contiguous_suffix() -> None:
    conversation = _conversation_with_completed_turns(2)
    current = conversation.start_turn(
        user_content="new",
        created_at=NOW + timedelta(seconds=5),
    ).user_message
    builder = ConversationContextBuilder(max_messages=10, max_characters=14)

    request = builder.build(
        completed_history=conversation.messages[:-1],
        current_user_message=current,
        correlation_id="request-2",
        context_limit=10,
    )

    assert [message.content for message in request.messages] == [
        "assistant-1",
        "new",
    ]


def test_context_rejects_non_user_current_message_and_oversized_input() -> None:
    conversation = _conversation_with_completed_turns(1)
    assistant = conversation.messages[-1]

    with pytest.raises(ValueError, match="user role"):
        ConversationContextBuilder().build(
            completed_history=(),
            current_user_message=assistant,
            correlation_id="request-3",
            context_limit=1,
        )

    current = conversation.start_turn(
        user_content="too long",
        created_at=NOW + timedelta(seconds=3),
    ).user_message
    assert current.role is MessageRole.USER
    with pytest.raises(ValueError, match="context budget"):
        ConversationContextBuilder(max_characters=2).build(
            completed_history=(),
            current_user_message=current,
            correlation_id="request-4",
            context_limit=1,
        )
