"""Centralized conversion between conversation domain entities and ORM rows."""

from collections.abc import Sequence
from uuid import UUID

from app.domain.conversations import (
    Conversation,
    ConversationStatus,
    ConversationTurn,
    InvalidDomainValueError,
    Message,
    MessageRole,
    TokenUsage,
    TurnMessageConflictError,
    TurnStatus,
)
from app.models.conversations import (
    ConversationModel,
    ConversationTurnModel,
    MessageModel,
)


def message_to_model(message: Message) -> MessageModel:
    """Create an ORM row from one validated domain message."""

    return MessageModel(
        id=message.id,
        conversation_id=message.conversation_id,
        turn_id=message.turn_id,
        role=message.role.value,
        content=message.content,
        sequence=message.sequence,
        created_at=message.created_at,
    )


def message_to_domain(model: MessageModel) -> Message:
    """Restore one domain message and re-run its value validation."""

    try:
        role = MessageRole(model.role)
    except ValueError as exc:
        raise InvalidDomainValueError("Persisted message role is invalid") from exc
    return Message(
        id=model.id,
        conversation_id=model.conversation_id,
        turn_id=model.turn_id,
        role=role,
        content=model.content,
        sequence=model.sequence,
        created_at=model.created_at,
    )


def turn_to_model(turn: ConversationTurn) -> ConversationTurnModel:
    """Create an ORM row containing only normalized turn result fields."""

    usage = turn.usage
    return ConversationTurnModel(
        id=turn.id,
        conversation_id=turn.conversation_id,
        sequence=turn.sequence,
        request_id=turn.request_id,
        idempotency_key=turn.idempotency_key,
        status=turn.status.value,
        provider_name=turn.provider_name,
        model_name=turn.model_name,
        finish_reason=turn.finish_reason,
        prompt_tokens=None if usage is None else usage.prompt_tokens,
        completion_tokens=None if usage is None else usage.completion_tokens,
        total_tokens=None if usage is None else usage.total_tokens,
        safe_error_code=turn.safe_error_code,
        created_at=turn.created_at,
        updated_at=turn.updated_at,
        completed_at=turn.completed_at,
    )


def turn_to_domain(
    model: ConversationTurnModel,
    messages: Sequence[MessageModel],
) -> ConversationTurn:
    """Restore a turn through the domain's validated rehydration path."""

    domain_messages = tuple(message_to_domain(message) for message in messages)
    return _turn_to_domain(model, domain_messages)


def _turn_to_domain(
    model: ConversationTurnModel,
    domain_messages: Sequence[Message],
) -> ConversationTurn:
    user_messages = tuple(
        message for message in domain_messages if message.role is MessageRole.USER
    )
    assistant_messages = tuple(
        message
        for message in domain_messages
        if message.role is MessageRole.ASSISTANT
    )
    if len(user_messages) != 1 or len(assistant_messages) > 1:
        raise TurnMessageConflictError(
            "Persisted turn must contain one user and at most one assistant message"
        )
    try:
        status = TurnStatus(model.status)
    except ValueError as exc:
        raise InvalidDomainValueError("Persisted turn status is invalid") from exc
    usage = None
    if any(
        value is not None
        for value in (
            model.prompt_tokens,
            model.completion_tokens,
            model.total_tokens,
        )
    ):
        usage = TokenUsage(
            prompt_tokens=model.prompt_tokens,
            completion_tokens=model.completion_tokens,
            total_tokens=model.total_tokens,
        )
    return ConversationTurn.rehydrate(
        turn_id=model.id,
        conversation_id=model.conversation_id,
        sequence=model.sequence,
        user_message=user_messages[0],
        assistant_message=assistant_messages[0] if assistant_messages else None,
        request_id=model.request_id,
        idempotency_key=model.idempotency_key,
        status=status,
        provider_name=model.provider_name,
        model_name=model.model_name,
        finish_reason=model.finish_reason,
        usage=usage,
        safe_error_code=model.safe_error_code,
        created_at=model.created_at,
        updated_at=model.updated_at,
        completed_at=model.completed_at,
    )


def conversation_to_model(conversation: Conversation) -> ConversationModel:
    """Create an ORM aggregate-root row without persisting child rows."""

    return ConversationModel(
        id=conversation.id,
        title=conversation.title,
        status=conversation.status.value,
        next_sequence=conversation.next_sequence,
        created_at=conversation.created_at,
        updated_at=conversation.updated_at,
        archived_at=conversation.archived_at,
    )


def conversation_to_domain(
    model: ConversationModel,
    turns: Sequence[ConversationTurnModel],
    messages: Sequence[MessageModel],
) -> Conversation:
    """Restore an aggregate without exposing or returning ORM objects."""

    domain_messages = tuple(message_to_domain(message) for message in messages)
    messages_by_turn: dict[UUID, list[Message]] = {}
    for message in domain_messages:
        messages_by_turn.setdefault(message.turn_id, []).append(message)
    domain_turns = tuple(
        _turn_to_domain(turn, messages_by_turn.get(turn.id, ())) for turn in turns
    )
    try:
        status = ConversationStatus(model.status)
    except ValueError as exc:
        raise InvalidDomainValueError(
            "Persisted conversation status is invalid"
        ) from exc
    return Conversation.rehydrate(
        conversation_id=model.id,
        title=model.title,
        status=status,
        next_sequence=model.next_sequence,
        created_at=model.created_at,
        updated_at=model.updated_at,
        archived_at=model.archived_at,
        turns=domain_turns,
        messages=domain_messages,
    )
