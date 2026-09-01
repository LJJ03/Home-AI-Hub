"""Pure offline round-trip tests for conversation persistence mappers."""

from datetime import UTC, datetime, timedelta

import pytest

from app.domain.conversations import (
    Conversation,
    ConversationStatus,
    InvalidDomainValueError,
    TokenUsage,
    TurnStatus,
)
from app.repositories.conversation_mappers import (
    conversation_to_domain,
    conversation_to_model,
    message_to_model,
    turn_to_domain,
    turn_to_model,
)


NOW = datetime(2026, 9, 1, 9, 0, tzinfo=UTC)


def _completed_conversation() -> Conversation:
    conversation = Conversation.create(title="Mapped conversation", created_at=NOW)
    turn = conversation.start_turn(
        user_content="private user content",
        request_id="request-one",
        idempotency_key="idempotency-one",
        created_at=NOW + timedelta(seconds=1),
    )
    conversation.complete_turn(
        turn.id,
        assistant_content="private assistant content",
        provider_name="mock",
        model_name="mock-default",
        finish_reason="stop",
        usage=TokenUsage(
            prompt_tokens=3,
            completion_tokens=5,
            total_tokens=8,
        ),
        completed_at=NOW + timedelta(seconds=2),
    )
    return conversation


def test_mapper_round_trip_restores_a_valid_archived_aggregate() -> None:
    conversation = _completed_conversation()
    conversation.archive(archived_at=NOW + timedelta(seconds=3))

    restored = conversation_to_domain(
        conversation_to_model(conversation),
        [turn_to_model(turn) for turn in conversation.turns],
        [message_to_model(message) for message in conversation.messages],
    )

    assert restored.id == conversation.id
    assert restored.status is ConversationStatus.ARCHIVED
    assert restored.archived_at == NOW + timedelta(seconds=3)
    assert restored.next_sequence == 3
    assert len(restored.turns) == 1
    assert restored.turns[0].status is TurnStatus.COMPLETED
    assert restored.turns[0].usage == TokenUsage(3, 5, 8)
    assert [message.sequence for message in restored.messages] == [1, 2]
    assert all("private" not in repr(message) for message in restored.messages)


@pytest.mark.parametrize("terminal_status", ("failed", "cancelled"))
def test_turn_mapper_restores_non_success_terminal_states(
    terminal_status: str,
) -> None:
    conversation = Conversation.create(created_at=NOW)
    turn = conversation.start_turn(
        user_content="safe test input",
        created_at=NOW + timedelta(seconds=1),
    )
    if terminal_status == "failed":
        conversation.fail_turn(
            turn.id,
            safe_error_code="provider_unavailable",
            provider_name="mock",
            model_name="mock-default",
            completed_at=NOW + timedelta(seconds=2),
        )
    else:
        conversation.cancel_turn(
            turn.id,
            completed_at=NOW + timedelta(seconds=2),
        )

    restored = turn_to_domain(
        turn_to_model(turn),
        [message_to_model(turn.user_message)],
    )

    assert restored.status.value == terminal_status
    assert restored.completed_at == NOW + timedelta(seconds=2)


def test_mapper_rejects_an_invalid_persisted_pending_result() -> None:
    conversation = Conversation.create(created_at=NOW)
    turn = conversation.start_turn(
        user_content="safe test input",
        created_at=NOW + timedelta(seconds=1),
    )
    turn_model = turn_to_model(turn)
    turn_model.provider_name = "unexpected-provider"

    with pytest.raises(
        InvalidDomainValueError,
        match="Pending turns cannot contain terminal result fields",
    ):
        turn_to_domain(turn_model, [message_to_model(turn.user_message)])
