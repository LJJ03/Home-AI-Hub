"""SQLAlchemy adapters for the conversation repository protocols."""

from collections.abc import Sequence
from uuid import UUID

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.conversations import Conversation, ConversationTurn, Message, TurnStatus
from app.models.conversations import (
    ConversationModel,
    ConversationTurnModel,
    MessageModel,
)
from app.repositories.conversation_mappers import (
    conversation_to_domain,
    conversation_to_model,
    message_to_domain,
    message_to_model,
    turn_to_domain,
    turn_to_model,
)


def _validate_limit(limit: int, *, maximum: int = 100) -> None:
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= maximum:
        raise ValueError(f"limit must be between 1 and {maximum}")


class SqlAlchemyConversationRepository:
    """Load and persist aggregate roots using one injected session."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, conversation: Conversation) -> None:
        self._session.add(conversation_to_model(conversation))
        await self._session.flush()

    async def get_by_id(self, conversation_id: UUID) -> Conversation | None:
        model = await self._session.get(ConversationModel, conversation_id)
        if model is None:
            return None
        return await self._load_domain(model)

    async def list(
        self,
        *,
        offset: int = 0,
        limit: int = 50,
    ) -> Sequence[Conversation]:
        if isinstance(offset, bool) or not isinstance(offset, int) or offset < 0:
            raise ValueError("offset must be a non-negative integer")
        _validate_limit(limit)
        statement = (
            select(ConversationModel)
            .order_by(
                ConversationModel.updated_at.desc(),
                ConversationModel.id.asc(),
            )
            .offset(offset)
            .limit(limit)
        )
        models = (await self._session.scalars(statement)).all()
        return tuple([await self._load_domain(model) for model in models])

    async def save(self, conversation: Conversation) -> None:
        model = await self._session.get(ConversationModel, conversation.id)
        if model is None:
            raise LookupError("Conversation was not found")
        model.title = conversation.title
        model.status = conversation.status.value
        model.next_sequence = conversation.next_sequence
        model.updated_at = conversation.updated_at
        model.archived_at = conversation.archived_at
        await self._session.flush()

    async def get_for_update(
        self,
        conversation_id: UUID,
    ) -> Conversation | None:
        statement = (
            select(ConversationModel)
            .where(ConversationModel.id == conversation_id)
            .with_for_update()
        )
        model = await self._session.scalar(statement)
        if model is None:
            return None
        return await self._load_domain(model)

    async def _load_domain(self, model: ConversationModel) -> Conversation:
        turn_statement = (
            select(ConversationTurnModel)
            .where(ConversationTurnModel.conversation_id == model.id)
            .order_by(ConversationTurnModel.sequence.asc())
        )
        message_statement = (
            select(MessageModel)
            .where(MessageModel.conversation_id == model.id)
            .order_by(MessageModel.sequence.asc())
        )
        turns = (await self._session.scalars(turn_statement)).all()
        messages = (await self._session.scalars(message_statement)).all()
        return conversation_to_domain(model, turns, messages)


class SqlAlchemyConversationTurnRepository:
    """Persist normalized turn state without committing the session."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, turn: ConversationTurn) -> None:
        self._session.add(turn_to_model(turn))
        await self._session.flush()

    async def get_by_id(self, turn_id: UUID) -> ConversationTurn | None:
        model = await self._session.get(ConversationTurnModel, turn_id)
        if model is None:
            return None
        return await self._load_domain(model)

    async def get_by_idempotency_key(
        self,
        conversation_id: UUID,
        idempotency_key: str,
    ) -> ConversationTurn | None:
        if not isinstance(idempotency_key, str) or not idempotency_key.strip():
            raise ValueError("idempotency_key must not be blank")
        statement = select(ConversationTurnModel).where(
            ConversationTurnModel.conversation_id == conversation_id,
            ConversationTurnModel.idempotency_key == idempotency_key.strip(),
        )
        model = await self._session.scalar(statement)
        if model is None:
            return None
        return await self._load_domain(model)

    async def list_pending(
        self,
        conversation_id: UUID,
        *,
        limit: int = 100,
    ) -> Sequence[ConversationTurn]:
        _validate_limit(limit)
        statement = (
            select(ConversationTurnModel)
            .where(
                ConversationTurnModel.conversation_id == conversation_id,
                ConversationTurnModel.status == TurnStatus.PENDING.value,
            )
            .order_by(ConversationTurnModel.sequence.asc())
            .limit(limit)
        )
        models = (await self._session.scalars(statement)).all()
        return tuple([await self._load_domain(model) for model in models])

    async def save(self, turn: ConversationTurn) -> None:
        model = await self._session.get(ConversationTurnModel, turn.id)
        if model is None:
            raise LookupError("Conversation turn was not found")
        mapped = turn_to_model(turn)
        model.request_id = mapped.request_id
        model.idempotency_key = mapped.idempotency_key
        model.status = mapped.status
        model.provider_name = mapped.provider_name
        model.model_name = mapped.model_name
        model.finish_reason = mapped.finish_reason
        model.prompt_tokens = mapped.prompt_tokens
        model.completion_tokens = mapped.completion_tokens
        model.total_tokens = mapped.total_tokens
        model.safe_error_code = mapped.safe_error_code
        model.updated_at = mapped.updated_at
        model.completed_at = mapped.completed_at
        await self._session.flush()

    async def _load_domain(
        self,
        model: ConversationTurnModel,
    ) -> ConversationTurn:
        statement = (
            select(MessageModel)
            .where(MessageModel.turn_id == model.id)
            .order_by(MessageModel.sequence.asc())
        )
        messages = (await self._session.scalars(statement)).all()
        return turn_to_domain(model, messages)


class SqlAlchemyMessageRepository:
    """Persist and read ordered messages without owning commit behavior."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, message: Message) -> None:
        self._session.add(message_to_model(message))
        await self._session.flush()

    async def list_by_conversation(
        self,
        conversation_id: UUID,
        *,
        after_sequence: int | None = None,
        limit: int = 100,
    ) -> Sequence[Message]:
        _validate_limit(limit)
        if after_sequence is not None and (
            isinstance(after_sequence, bool)
            or not isinstance(after_sequence, int)
            or after_sequence < 0
        ):
            raise ValueError("after_sequence must be a non-negative integer")
        statement = select(MessageModel).where(
            MessageModel.conversation_id == conversation_id
        )
        if after_sequence is not None:
            statement = statement.where(MessageModel.sequence > after_sequence)
        statement = statement.order_by(MessageModel.sequence.asc()).limit(limit)
        models = (await self._session.scalars(statement)).all()
        return tuple(message_to_domain(model) for model in models)

    async def list_recent_completed_for_context(
        self,
        conversation_id: UUID,
        *,
        limit: int = 20,
    ) -> Sequence[Message]:
        _validate_limit(limit)
        statement = (
            select(MessageModel)
            .join(
                ConversationTurnModel,
                and_(
                    MessageModel.turn_id == ConversationTurnModel.id,
                    MessageModel.conversation_id
                    == ConversationTurnModel.conversation_id,
                ),
            )
            .where(
                MessageModel.conversation_id == conversation_id,
                ConversationTurnModel.status == TurnStatus.COMPLETED.value,
            )
            .order_by(MessageModel.sequence.desc())
            .limit(limit)
        )
        models = list((await self._session.scalars(statement)).all())
        models.reverse()
        return tuple(message_to_domain(model) for model in models)

    async def next_sequence(self, conversation_id: UUID) -> int | None:
        statement = select(ConversationModel.next_sequence).where(
            ConversationModel.id == conversation_id
        )
        return await self._session.scalar(statement)
