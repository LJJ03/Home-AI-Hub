"""Cross-entity aggregate invariant tests."""

from datetime import UTC, datetime, timedelta
from itertools import pairwise

import pytest

from app.domain.conversations import (
    Conversation,
    IdempotencyConflictError,
    InvalidDomainValueError,
    InvalidTurnTransitionError,
)


CREATED_AT = datetime(2026, 9, 1, 11, 0, tzinfo=UTC)


def test_conversation_message_sequences_are_strictly_monotonic() -> None:
    conversation = Conversation.create(created_at=CREATED_AT)
    first_turn = conversation.start_turn(
        user_content="First user message",
        created_at=CREATED_AT + timedelta(seconds=1),
    )
    conversation.complete_turn(
        first_turn.id,
        assistant_content="First assistant message",
        completed_at=CREATED_AT + timedelta(seconds=2),
    )
    conversation.start_turn(
        user_content="Second user message",
        created_at=CREATED_AT + timedelta(seconds=3),
    )

    assert [message.sequence for message in conversation.messages] == [1, 2, 3]
    assert all(
        current.sequence < following.sequence
        for current, following in pairwise(conversation.messages)
    )


def test_turn_has_exactly_one_user_and_at_most_one_assistant_message() -> None:
    conversation = Conversation.create(created_at=CREATED_AT)
    turn = conversation.start_turn(
        user_content="One user message",
        created_at=CREATED_AT + timedelta(seconds=1),
    )
    conversation.complete_turn(
        turn.id,
        assistant_content="One assistant message",
        completed_at=CREATED_AT + timedelta(seconds=2),
    )

    with pytest.raises(InvalidTurnTransitionError):
        conversation.complete_turn(
            turn.id,
            assistant_content="A second assistant must be rejected",
            completed_at=CREATED_AT + timedelta(seconds=3),
        )

    assert len(turn.messages) == 2
    assert len(conversation.messages) == 2


def test_idempotency_key_is_unique_within_conversation() -> None:
    conversation = Conversation.create(created_at=CREATED_AT)
    conversation.start_turn(
        user_content="First operation",
        idempotency_key="unique-operation",
        created_at=CREATED_AT + timedelta(seconds=1),
    )

    with pytest.raises(IdempotencyConflictError):
        conversation.start_turn(
            user_content="Duplicate operation",
            idempotency_key="unique-operation",
            created_at=CREATED_AT + timedelta(seconds=2),
        )

    assert len(conversation.turns) == 1
    assert len(conversation.messages) == 1


def test_domain_rejects_naive_timestamps() -> None:
    with pytest.raises(InvalidDomainValueError):
        Conversation.create(created_at=datetime(2026, 9, 1, 11, 0))
