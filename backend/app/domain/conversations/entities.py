"""Conversation aggregate entities and invariant-preserving operations."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from app.domain.conversations.enums import (
    ConversationStatus,
    MessageRole,
    TurnStatus,
)
from app.domain.conversations.errors import (
    ConversationArchivedError,
    IdempotencyConflictError,
    InvalidDomainValueError,
    InvalidMessageRoleError,
    InvalidTurnTransitionError,
    MessageContentError,
    MessageOwnershipError,
    MessageSequenceError,
    TurnMessageConflictError,
    TurnNotFoundError,
)
from app.domain.conversations.value_objects import (
    TokenUsage,
    as_utc,
    new_domain_id,
    optional_text,
    positive_sequence,
    require_uuid,
    resolve_utc,
)


@dataclass(frozen=True, slots=True, repr=False)
class Message:
    """An accepted user or final assistant message with safe representation."""

    id: UUID
    conversation_id: UUID
    turn_id: UUID
    role: MessageRole
    content: str
    sequence: int
    created_at: datetime

    def __post_init__(self) -> None:
        require_uuid(self.id, field_name="message id")
        require_uuid(self.conversation_id, field_name="conversation id")
        require_uuid(self.turn_id, field_name="turn id")
        if not isinstance(self.role, MessageRole):
            raise InvalidMessageRoleError("Message role must be user or assistant")
        if not isinstance(self.content, str) or not self.content.strip():
            raise MessageContentError("Message content must not be blank")
        positive_sequence(self.sequence, field_name="message sequence")
        object.__setattr__(
            self,
            "created_at",
            as_utc(self.created_at, field_name="message created_at"),
        )

    @classmethod
    def create(
        cls,
        *,
        conversation_id: UUID,
        turn_id: UUID,
        role: MessageRole,
        content: str,
        sequence: int,
        created_at: datetime,
    ) -> Message:
        """Create a new message with an unpredictable identifier."""

        return cls(
            id=new_domain_id(),
            conversation_id=conversation_id,
            turn_id=turn_id,
            role=role,
            content=content,
            sequence=sequence,
            created_at=created_at,
        )

    def __repr__(self) -> str:
        """Keep message content out of logs and diagnostic representations."""

        return (
            "Message("
            f"id={self.id!r}, role={self.role!r}, sequence={self.sequence!r}, "
            "content=<redacted>)"
        )


class ConversationTurn:
    """One model-generation operation owned by a conversation aggregate."""

    __slots__ = (
        "_assistant_message",
        "_completed_at",
        "_conversation_id",
        "_created_at",
        "_finish_reason",
        "_id",
        "_idempotency_key",
        "_model_name",
        "_provider_name",
        "_request_id",
        "_safe_error_code",
        "_sequence",
        "_status",
        "_updated_at",
        "_usage",
        "_user_message",
    )

    def __init__(
        self,
        *,
        turn_id: UUID,
        conversation_id: UUID,
        sequence: int,
        user_message: Message,
        request_id: str | None,
        idempotency_key: str | None,
        created_at: datetime,
    ) -> None:
        self._id = require_uuid(turn_id, field_name="turn id")
        self._conversation_id = require_uuid(
            conversation_id,
            field_name="conversation id",
        )
        self._sequence = positive_sequence(sequence, field_name="turn sequence")
        self._request_id = optional_text(
            request_id,
            field_name="request_id",
            max_length=128,
        )
        self._idempotency_key = optional_text(
            idempotency_key,
            field_name="idempotency_key",
            max_length=255,
        )
        if (
            self._request_id is not None
            and self._idempotency_key is not None
            and self._request_id == self._idempotency_key
        ):
            raise InvalidDomainValueError(
                "request_id and idempotency_key must be distinct"
            )
        timestamp = as_utc(created_at, field_name="turn created_at")
        self._validate_message(user_message, expected_role=MessageRole.USER)
        self._user_message = user_message
        self._assistant_message: Message | None = None
        self._status = TurnStatus.PENDING
        self._provider_name: str | None = None
        self._model_name: str | None = None
        self._finish_reason: str | None = None
        self._usage: TokenUsage | None = None
        self._safe_error_code: str | None = None
        self._created_at = timestamp
        self._updated_at = timestamp
        self._completed_at: datetime | None = None

    @property
    def id(self) -> UUID:
        return self._id

    @property
    def conversation_id(self) -> UUID:
        return self._conversation_id

    @property
    def sequence(self) -> int:
        return self._sequence

    @property
    def status(self) -> TurnStatus:
        return self._status

    @property
    def request_id(self) -> str | None:
        return self._request_id

    @property
    def idempotency_key(self) -> str | None:
        return self._idempotency_key

    @property
    def provider_name(self) -> str | None:
        return self._provider_name

    @property
    def model_name(self) -> str | None:
        return self._model_name

    @property
    def finish_reason(self) -> str | None:
        return self._finish_reason

    @property
    def usage(self) -> TokenUsage | None:
        return self._usage

    @property
    def safe_error_code(self) -> str | None:
        return self._safe_error_code

    @property
    def created_at(self) -> datetime:
        return self._created_at

    @property
    def updated_at(self) -> datetime:
        return self._updated_at

    @property
    def completed_at(self) -> datetime | None:
        return self._completed_at

    @property
    def user_message(self) -> Message:
        return self._user_message

    @property
    def assistant_message(self) -> Message | None:
        return self._assistant_message

    @property
    def messages(self) -> tuple[Message, ...]:
        if self._assistant_message is None:
            return (self._user_message,)
        return (self._user_message, self._assistant_message)

    def _complete(
        self,
        *,
        assistant_message: Message,
        provider_name: str | None,
        model_name: str | None,
        finish_reason: str | None,
        usage: TokenUsage | None,
        completed_at: datetime,
    ) -> None:
        self._require_pending(TurnStatus.COMPLETED)
        if self._assistant_message is not None:
            raise TurnMessageConflictError(
                "A turn can contain at most one assistant message"
            )
        self._validate_message(
            assistant_message,
            expected_role=MessageRole.ASSISTANT,
        )
        if assistant_message.sequence <= self._user_message.sequence:
            raise MessageSequenceError(
                "Assistant message sequence must follow the user message"
            )
        normalized_provider = optional_text(
            provider_name,
            field_name="provider_name",
            max_length=64,
        )
        normalized_model = optional_text(
            model_name,
            field_name="model_name",
            max_length=255,
        )
        normalized_finish_reason = optional_text(
            finish_reason,
            field_name="finish_reason",
            max_length=64,
        )
        if usage is not None and not isinstance(usage, TokenUsage):
            raise InvalidDomainValueError("usage must be TokenUsage")
        timestamp = self._terminal_timestamp(completed_at)

        self._assistant_message = assistant_message
        self._provider_name = normalized_provider
        self._model_name = normalized_model
        self._finish_reason = normalized_finish_reason
        self._usage = usage
        self._safe_error_code = None
        self._status = TurnStatus.COMPLETED
        self._updated_at = timestamp
        self._completed_at = timestamp

    def _fail(
        self,
        *,
        safe_error_code: str | None,
        provider_name: str | None,
        model_name: str | None,
        completed_at: datetime,
    ) -> None:
        self._require_pending(TurnStatus.FAILED)
        normalized_error = optional_text(
            safe_error_code,
            field_name="safe_error_code",
            max_length=128,
        )
        normalized_provider = optional_text(
            provider_name,
            field_name="provider_name",
            max_length=64,
        )
        normalized_model = optional_text(
            model_name,
            field_name="model_name",
            max_length=255,
        )
        timestamp = self._terminal_timestamp(completed_at)

        self._provider_name = normalized_provider
        self._model_name = normalized_model
        self._safe_error_code = normalized_error
        self._status = TurnStatus.FAILED
        self._updated_at = timestamp
        self._completed_at = timestamp

    def _cancel(self, *, completed_at: datetime) -> None:
        self._require_pending(TurnStatus.CANCELLED)
        timestamp = self._terminal_timestamp(completed_at)
        self._status = TurnStatus.CANCELLED
        self._updated_at = timestamp
        self._completed_at = timestamp

    def _validate_message(
        self,
        message: Message,
        *,
        expected_role: MessageRole,
    ) -> None:
        if not isinstance(message, Message):
            raise InvalidDomainValueError("turn messages must be Message entities")
        if message.conversation_id != self._conversation_id:
            raise MessageOwnershipError(
                "Message must belong to the turn's conversation"
            )
        if message.turn_id != self._id:
            raise MessageOwnershipError("Message must belong to the turn")
        if message.role is not expected_role:
            raise TurnMessageConflictError(
                f"Turn message must have role {expected_role.value}"
            )

    def _require_pending(self, target: TurnStatus) -> None:
        if self._status is not TurnStatus.PENDING:
            raise InvalidTurnTransitionError(
                f"Cannot transition turn from {self._status.value} to {target.value}"
            )

    def _terminal_timestamp(self, value: datetime) -> datetime:
        timestamp = as_utc(value, field_name="turn completed_at")
        if timestamp < self._updated_at:
            raise InvalidDomainValueError("Turn time cannot move backwards")
        return timestamp

    def __repr__(self) -> str:
        return (
            "ConversationTurn("
            f"id={self._id!r}, sequence={self._sequence!r}, "
            f"status={self._status!r}, messages={len(self.messages)})"
        )


class Conversation:
    """Aggregate root for conversation lifecycle, turns, and message ordering."""

    __slots__ = (
        "_archived_at",
        "_created_at",
        "_id",
        "_messages",
        "_next_message_sequence",
        "_next_turn_sequence",
        "_status",
        "_title",
        "_turns",
        "_updated_at",
    )

    def __init__(
        self,
        *,
        conversation_id: UUID,
        title: str | None,
        created_at: datetime,
    ) -> None:
        self._id = require_uuid(conversation_id, field_name="conversation id")
        self._title = optional_text(title, field_name="title", max_length=200)
        timestamp = as_utc(created_at, field_name="conversation created_at")
        self._status = ConversationStatus.ACTIVE
        self._created_at = timestamp
        self._updated_at = timestamp
        self._archived_at: datetime | None = None
        self._turns: list[ConversationTurn] = []
        self._messages: list[Message] = []
        self._next_turn_sequence = 1
        self._next_message_sequence = 1

    @classmethod
    def create(
        cls,
        *,
        title: str | None = None,
        created_at: datetime | None = None,
    ) -> Conversation:
        """Create a new active aggregate with UUID4 identity and UTC time."""

        return cls(
            conversation_id=new_domain_id(),
            title=title,
            created_at=resolve_utc(
                created_at,
                field_name="conversation created_at",
            ),
        )

    @property
    def id(self) -> UUID:
        return self._id

    @property
    def title(self) -> str | None:
        return self._title

    @property
    def status(self) -> ConversationStatus:
        return self._status

    @property
    def created_at(self) -> datetime:
        return self._created_at

    @property
    def updated_at(self) -> datetime:
        return self._updated_at

    @property
    def archived_at(self) -> datetime | None:
        return self._archived_at

    @property
    def turns(self) -> tuple[ConversationTurn, ...]:
        return tuple(self._turns)

    @property
    def messages(self) -> tuple[Message, ...]:
        return tuple(self._messages)

    def archive(self, *, archived_at: datetime | None = None) -> None:
        """Archive the aggregate; repeated archival is intentionally idempotent."""

        if self._status is ConversationStatus.ARCHIVED:
            return
        timestamp = self._change_timestamp(
            archived_at,
            field_name="conversation archived_at",
        )
        self._status = ConversationStatus.ARCHIVED
        self._archived_at = timestamp
        self._updated_at = timestamp

    def start_turn(
        self,
        *,
        user_content: str,
        request_id: str | None = None,
        idempotency_key: str | None = None,
        created_at: datetime | None = None,
    ) -> ConversationTurn:
        """Append one pending turn and its required user message atomically."""

        self._require_active()
        timestamp = self._change_timestamp(
            created_at,
            field_name="turn created_at",
        )
        turn_id = new_domain_id()
        user_message = Message.create(
            conversation_id=self._id,
            turn_id=turn_id,
            role=MessageRole.USER,
            content=user_content,
            sequence=self._next_message_sequence,
            created_at=timestamp,
        )
        turn = ConversationTurn(
            turn_id=turn_id,
            conversation_id=self._id,
            sequence=self._next_turn_sequence,
            user_message=user_message,
            request_id=request_id,
            idempotency_key=idempotency_key,
            created_at=timestamp,
        )
        if turn.idempotency_key is not None and any(
            existing.idempotency_key == turn.idempotency_key
            for existing in self._turns
        ):
            raise IdempotencyConflictError(
                "Idempotency key already belongs to this conversation"
            )

        self._turns.append(turn)
        self._messages.append(user_message)
        self._next_turn_sequence += 1
        self._next_message_sequence += 1
        self._updated_at = timestamp
        return turn

    def complete_turn(
        self,
        turn_id: UUID,
        *,
        assistant_content: str,
        provider_name: str | None = None,
        model_name: str | None = None,
        finish_reason: str | None = None,
        usage: TokenUsage | None = None,
        completed_at: datetime | None = None,
    ) -> ConversationTurn:
        """Append one final assistant message and complete its pending turn."""

        self._require_active()
        turn = self._turn(turn_id)
        timestamp = self._change_timestamp(
            completed_at,
            field_name="turn completed_at",
        )
        assistant_message = Message.create(
            conversation_id=self._id,
            turn_id=turn.id,
            role=MessageRole.ASSISTANT,
            content=assistant_content,
            sequence=self._next_message_sequence,
            created_at=timestamp,
        )
        turn._complete(
            assistant_message=assistant_message,
            provider_name=provider_name,
            model_name=model_name,
            finish_reason=finish_reason,
            usage=usage,
            completed_at=timestamp,
        )
        self._messages.append(assistant_message)
        self._next_message_sequence += 1
        self._updated_at = timestamp
        return turn

    def fail_turn(
        self,
        turn_id: UUID,
        *,
        safe_error_code: str | None = None,
        provider_name: str | None = None,
        model_name: str | None = None,
        completed_at: datetime | None = None,
    ) -> ConversationTurn:
        """Mark a pending turn failed without persisting provider details."""

        turn = self._turn(turn_id)
        timestamp = self._change_timestamp(
            completed_at,
            field_name="turn completed_at",
        )
        turn._fail(
            safe_error_code=safe_error_code,
            provider_name=provider_name,
            model_name=model_name,
            completed_at=timestamp,
        )
        self._updated_at = timestamp
        return turn

    def cancel_turn(
        self,
        turn_id: UUID,
        *,
        completed_at: datetime | None = None,
    ) -> ConversationTurn:
        """Mark a pending turn cancelled without adding an assistant message."""

        turn = self._turn(turn_id)
        timestamp = self._change_timestamp(
            completed_at,
            field_name="turn completed_at",
        )
        turn._cancel(completed_at=timestamp)
        self._updated_at = timestamp
        return turn

    def _turn(self, turn_id: UUID) -> ConversationTurn:
        normalized_id = require_uuid(turn_id, field_name="turn id")
        for turn in self._turns:
            if turn.id == normalized_id:
                return turn
        raise TurnNotFoundError("Turn does not belong to this conversation")

    def _require_active(self) -> None:
        if self._status is ConversationStatus.ARCHIVED:
            raise ConversationArchivedError(
                "Archived conversations cannot accept new messages or turns"
            )

    def _change_timestamp(
        self,
        value: datetime | None,
        *,
        field_name: str,
    ) -> datetime:
        timestamp = resolve_utc(value, field_name=field_name)
        if timestamp < self._updated_at:
            raise InvalidDomainValueError("Conversation time cannot move backwards")
        return timestamp

    def __repr__(self) -> str:
        return (
            "Conversation("
            f"id={self._id!r}, status={self._status!r}, "
            f"turns={len(self._turns)}, messages={len(self._messages)})"
        )
