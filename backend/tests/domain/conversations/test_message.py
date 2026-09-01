"""Message validation and content-safety tests."""

import logging
from datetime import UTC, datetime, timedelta
from typing import cast
from uuid import uuid4

import pytest

from app.domain.conversations import (
    Conversation,
    InvalidMessageRoleError,
    Message,
    MessageContentError,
    MessageRole,
    TurnStatus,
)


CREATED_AT = datetime(2026, 9, 1, 10, 0, tzinfo=UTC)


@pytest.mark.parametrize("content", ("", " ", "\t\r\n"))
def test_user_message_content_cannot_be_blank(content: str) -> None:
    conversation = Conversation.create(created_at=CREATED_AT)

    with pytest.raises(MessageContentError):
        conversation.start_turn(
            user_content=content,
            created_at=CREATED_AT + timedelta(seconds=1),
        )


@pytest.mark.parametrize("content", ("", " ", "\t\r\n"))
def test_assistant_message_content_cannot_be_blank(content: str) -> None:
    conversation = Conversation.create(created_at=CREATED_AT)
    turn = conversation.start_turn(
        user_content="Valid user content",
        created_at=CREATED_AT + timedelta(seconds=1),
    )

    with pytest.raises(MessageContentError):
        conversation.complete_turn(
            turn.id,
            assistant_content=content,
            completed_at=CREATED_AT + timedelta(seconds=2),
        )

    assert turn.status is TurnStatus.PENDING
    assert turn.assistant_message is None


def test_message_role_only_accepts_user_or_assistant() -> None:
    with pytest.raises(InvalidMessageRoleError):
        Message(
            id=uuid4(),
            conversation_id=uuid4(),
            turn_id=uuid4(),
            role=cast(MessageRole, "system"),
            content="Valid content",
            sequence=1,
            created_at=CREATED_AT,
        )


def test_message_representation_and_logs_redact_content(caplog: pytest.LogCaptureFixture) -> None:
    sensitive_content = "private household message body"
    conversation = Conversation.create(created_at=CREATED_AT)
    turn = conversation.start_turn(
        user_content=sensitive_content,
        created_at=CREATED_AT + timedelta(seconds=1),
    )

    with caplog.at_level(logging.INFO, logger="domain-repr-test"):
        logging.getLogger("domain-repr-test").info("%r", turn.user_message)

    assert sensitive_content not in repr(turn.user_message)
    assert sensitive_content not in repr(turn)
    assert sensitive_content not in repr(conversation)
    assert sensitive_content not in caplog.text
    assert "<redacted>" in repr(turn.user_message)

