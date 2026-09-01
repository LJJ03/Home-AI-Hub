"""Conversation aggregate lifecycle tests."""

from datetime import UTC, datetime, timedelta

import pytest

from app.domain.conversations import (
    Conversation,
    ConversationArchivedError,
    ConversationStatus,
    TurnStatus,
)


CREATED_AT = datetime(2026, 9, 1, 8, 0, tzinfo=UTC)


def test_create_active_conversation_with_uuid4_and_utc_timestamps() -> None:
    conversation = Conversation.create(
        title="Local conversation",
        created_at=CREATED_AT,
    )

    assert conversation.id.version == 4
    assert conversation.title == "Local conversation"
    assert conversation.status is ConversationStatus.ACTIVE
    assert conversation.created_at == CREATED_AT
    assert conversation.updated_at == CREATED_AT
    assert conversation.archived_at is None
    assert conversation.turns == ()
    assert conversation.messages == ()


def test_archive_conversation_sets_utc_archive_state() -> None:
    conversation = Conversation.create(created_at=CREATED_AT)
    archived_at = CREATED_AT + timedelta(minutes=1)

    conversation.archive(archived_at=archived_at)
    conversation.archive(archived_at=archived_at + timedelta(minutes=1))

    assert conversation.status is ConversationStatus.ARCHIVED
    assert conversation.archived_at == archived_at
    assert conversation.updated_at == archived_at


def test_archived_conversation_rejects_new_turns() -> None:
    conversation = Conversation.create(created_at=CREATED_AT)
    conversation.archive(archived_at=CREATED_AT + timedelta(minutes=1))

    with pytest.raises(ConversationArchivedError):
        conversation.start_turn(
            user_content="This write must be rejected",
            created_at=CREATED_AT + timedelta(minutes=2),
        )

    assert conversation.turns == ()
    assert conversation.messages == ()


def test_archived_conversation_rejects_new_assistant_message() -> None:
    conversation = Conversation.create(created_at=CREATED_AT)
    turn = conversation.start_turn(
        user_content="Archive before completion",
        created_at=CREATED_AT + timedelta(minutes=1),
    )
    conversation.archive(archived_at=CREATED_AT + timedelta(minutes=2))

    with pytest.raises(ConversationArchivedError):
        conversation.complete_turn(
            turn.id,
            assistant_content="This must not be appended",
            completed_at=CREATED_AT + timedelta(minutes=3),
        )

    assert turn.status is TurnStatus.PENDING
    assert len(conversation.messages) == 1

