"""Conversation turn lifecycle and metadata tests."""

from datetime import UTC, datetime, timedelta

import pytest

from app.domain.conversations import (
    Conversation,
    ConversationTurn,
    InvalidDomainValueError,
    InvalidTurnTransitionError,
    MessageRole,
    TokenUsage,
    TurnStatus,
)


CREATED_AT = datetime(2026, 9, 1, 9, 0, tzinfo=UTC)


def _pending_turn() -> tuple[Conversation, ConversationTurn]:
    conversation = Conversation.create(created_at=CREATED_AT)
    turn = conversation.start_turn(
        user_content="Generate a response",
        request_id="request-123",
        idempotency_key="idempotency-123",
        created_at=CREATED_AT + timedelta(seconds=1),
    )
    return conversation, turn


def test_start_turn_creates_pending_turn_with_one_user_message() -> None:
    conversation, turn = _pending_turn()

    assert turn.status is TurnStatus.PENDING
    assert turn.conversation_id == conversation.id
    assert turn.id.version == 4
    assert turn.sequence == 1
    assert turn.request_id == "request-123"
    assert turn.idempotency_key == "idempotency-123"
    assert turn.request_id != turn.idempotency_key
    assert turn.user_message.role is MessageRole.USER
    assert turn.assistant_message is None
    assert turn.messages == (turn.user_message,)


def test_complete_pending_turn_records_only_normalized_safe_metadata() -> None:
    conversation, turn = _pending_turn()
    usage = TokenUsage(
        prompt_tokens=7,
        completion_tokens=5,
        total_tokens=12,
    )

    completed = conversation.complete_turn(
        turn.id,
        assistant_content="Final response",
        provider_name="mock",
        model_name="mock-default",
        finish_reason="stop",
        usage=usage,
        completed_at=CREATED_AT + timedelta(seconds=2),
    )

    assert completed is turn
    assert turn.status is TurnStatus.COMPLETED
    assert turn.provider_name == "mock"
    assert turn.model_name == "mock-default"
    assert turn.finish_reason == "stop"
    assert turn.usage == usage
    assert turn.safe_error_code is None
    assert turn.assistant_message is not None
    assert turn.assistant_message.role is MessageRole.ASSISTANT
    assert turn.completed_at == CREATED_AT + timedelta(seconds=2)


def test_fail_pending_turn_records_safe_error_without_assistant_message() -> None:
    conversation, turn = _pending_turn()

    failed = conversation.fail_turn(
        turn.id,
        safe_error_code="llm_provider_unavailable",
        provider_name="mock",
        model_name="mock-default",
        completed_at=CREATED_AT + timedelta(seconds=2),
    )

    assert failed is turn
    assert turn.status is TurnStatus.FAILED
    assert turn.safe_error_code == "llm_provider_unavailable"
    assert turn.provider_name == "mock"
    assert turn.assistant_message is None
    assert len(conversation.messages) == 1


def test_cancel_pending_turn_adds_no_assistant_message() -> None:
    conversation, turn = _pending_turn()

    cancelled = conversation.cancel_turn(
        turn.id,
        completed_at=CREATED_AT + timedelta(seconds=2),
    )

    assert cancelled is turn
    assert turn.status is TurnStatus.CANCELLED
    assert turn.assistant_message is None
    assert len(conversation.messages) == 1


@pytest.mark.parametrize("terminal_state", tuple(TurnStatus)[1:])
def test_terminal_turn_rejects_additional_transition(
    terminal_state: TurnStatus,
) -> None:
    conversation, turn = _pending_turn()
    terminal_at = CREATED_AT + timedelta(seconds=2)
    if terminal_state is TurnStatus.COMPLETED:
        conversation.complete_turn(
            turn.id,
            assistant_content="Final response",
            completed_at=terminal_at,
        )
    elif terminal_state is TurnStatus.FAILED:
        conversation.fail_turn(turn.id, completed_at=terminal_at)
    else:
        conversation.cancel_turn(turn.id, completed_at=terminal_at)

    with pytest.raises(InvalidTurnTransitionError):
        conversation.cancel_turn(
            turn.id,
            completed_at=terminal_at + timedelta(seconds=1),
        )


def test_request_id_cannot_be_reused_as_idempotency_key() -> None:
    conversation = Conversation.create(created_at=CREATED_AT)

    with pytest.raises(InvalidDomainValueError):
        conversation.start_turn(
            user_content="Distinct correlation semantics",
            request_id="same-value",
            idempotency_key="same-value",
            created_at=CREATED_AT + timedelta(seconds=1),
        )

    assert conversation.turns == ()
