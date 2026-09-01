"""Conversation command, query, and non-streaming chat orchestration."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from datetime import UTC, datetime
from uuid import UUID, uuid4

from app.application.conversations.context_builder import ConversationContextBuilder
from app.application.conversations.dto import (
    ArchiveConversationCommand,
    ConversationChatCommand,
    ConversationChatResult,
    ConversationPage,
    ConversationView,
    CreateConversationCommand,
    MessagePage,
    MessageView,
    TokenUsageView,
)
from app.application.conversations.errors import (
    ConversationGenerationError,
    ConversationNotFoundError,
)
from app.application.conversations.ports import ConversationLLMService
from app.application.conversations.unit_of_work import ConversationUnitOfWork
from app.domain.conversations import (
    Conversation,
    ConversationTurn,
    Message,
    TokenUsage as DomainTokenUsage,
    TurnNotFoundError,
    TurnStatus,
)
from app.llm.exceptions import LLMException

UnitOfWorkFactory = Callable[[], ConversationUnitOfWork]
Clock = Callable[[], datetime]


def _utc_now() -> datetime:
    return datetime.now(UTC)


class ConversationCommandService:
    """Run conversation lifecycle commands without invoking an LLM."""

    def __init__(
        self,
        *,
        unit_of_work_factory: UnitOfWorkFactory,
        clock: Clock = _utc_now,
    ) -> None:
        self._unit_of_work_factory = unit_of_work_factory
        self._clock = clock

    async def create_conversation(
        self,
        command: CreateConversationCommand,
    ) -> ConversationView:
        conversation = Conversation.create(
            title=command.title,
            created_at=self._clock(),
        )
        async with self._unit_of_work_factory() as unit_of_work:
            await unit_of_work.conversation_repository.add(conversation)
            await unit_of_work.commit()
        return ConversationView.from_domain(conversation)

    async def archive_conversation(
        self,
        command: ArchiveConversationCommand,
    ) -> ConversationView:
        async with self._unit_of_work_factory() as unit_of_work:
            conversation = await unit_of_work.conversation_repository.get_for_update(
                command.conversation_id
            )
            if conversation is None:
                raise ConversationNotFoundError(command.conversation_id)
            conversation.archive(archived_at=self._clock())
            await unit_of_work.conversation_repository.save(conversation)
            await unit_of_work.commit()
        return ConversationView.from_domain(conversation)


class ConversationQueryService:
    """Return application DTOs without exposing ORM or mutable aggregates."""

    def __init__(self, *, unit_of_work_factory: UnitOfWorkFactory) -> None:
        self._unit_of_work_factory = unit_of_work_factory

    async def get_conversation(self, conversation_id: UUID) -> ConversationView:
        async with self._unit_of_work_factory() as unit_of_work:
            conversation = await unit_of_work.conversation_repository.get_by_id(
                conversation_id
            )
            if conversation is None:
                raise ConversationNotFoundError(conversation_id)
            return ConversationView.from_domain(conversation)

    async def list_conversations(
        self,
        *,
        offset: int = 0,
        limit: int = 50,
    ) -> ConversationPage:
        async with self._unit_of_work_factory() as unit_of_work:
            conversations = await unit_of_work.conversation_repository.list(
                offset=offset,
                limit=limit,
            )
            return ConversationPage(
                items=tuple(
                    ConversationView.from_domain(conversation)
                    for conversation in conversations
                ),
                offset=offset,
                limit=limit,
            )

    async def list_messages(
        self,
        conversation_id: UUID,
        *,
        after_sequence: int | None = None,
        limit: int = 100,
    ) -> MessagePage:
        async with self._unit_of_work_factory() as unit_of_work:
            conversation = await unit_of_work.conversation_repository.get_by_id(
                conversation_id
            )
            if conversation is None:
                raise ConversationNotFoundError(conversation_id)
            messages = await unit_of_work.message_repository.list_by_conversation(
                conversation_id,
                after_sequence=after_sequence,
                limit=limit,
            )
            items = tuple(MessageView.from_domain(message) for message in messages)
            return MessagePage(
                items=items,
                after_sequence=after_sequence,
                limit=limit,
                next_sequence=items[-1].sequence if items else None,
            )


class ConversationChatService:
    """Persist a user turn, call the LLM outside a transaction, then finalize."""

    def __init__(
        self,
        *,
        unit_of_work_factory: UnitOfWorkFactory,
        llm_service: ConversationLLMService,
        context_builder: ConversationContextBuilder | None = None,
        clock: Clock = _utc_now,
    ) -> None:
        self._unit_of_work_factory = unit_of_work_factory
        self._llm_service = llm_service
        self._context_builder = context_builder or ConversationContextBuilder()
        self._clock = clock

    async def complete(
        self,
        command: ConversationChatCommand,
    ) -> ConversationChatResult:
        request_id = command.request_id or uuid4().hex
        turn_id, user_message = await self._start_pending_turn(
            command=command,
            request_id=request_id,
        )
        bounded_context_limit = self._context_builder.bounded_limit(
            command.context_limit
        )
        completed_history = await self._load_completed_history(
            command.conversation_id,
            limit=bounded_context_limit,
        )
        try:
            request = self._context_builder.build(
                completed_history=completed_history,
                current_user_message=user_message,
                correlation_id=request_id,
                context_limit=bounded_context_limit,
                model_name=command.model_name,
                temperature=command.temperature,
                max_tokens=command.max_tokens,
            )
        except Exception:
            safe_code = "conversation_context_invalid"
            await self._best_effort_fail(
                conversation_id=command.conversation_id,
                turn_id=turn_id,
                safe_error_code=safe_code,
                provider_name=None,
                model_name=command.model_name,
            )
            raise ConversationGenerationError(code=safe_code) from None

        try:
            response = await self._llm_service.generate(request)
        except asyncio.CancelledError:
            await self._best_effort_cancel(
                conversation_id=command.conversation_id,
                turn_id=turn_id,
            )
            raise
        except LLMException as exc:
            await self._best_effort_fail(
                conversation_id=command.conversation_id,
                turn_id=turn_id,
                safe_error_code=exc.code,
                provider_name=exc.provider_name,
                model_name=command.model_name,
            )
            raise ConversationGenerationError(code=exc.code) from None
        except Exception:
            safe_code = "llm_generation_failed"
            await self._best_effort_fail(
                conversation_id=command.conversation_id,
                turn_id=turn_id,
                safe_error_code=safe_code,
                provider_name=None,
                model_name=command.model_name,
            )
            raise ConversationGenerationError(code=safe_code) from None

        if not response.text.strip():
            safe_code = "provider_invalid_response"
            await self._best_effort_fail(
                conversation_id=command.conversation_id,
                turn_id=turn_id,
                safe_error_code=safe_code,
                provider_name=response.provider_name,
                model_name=response.model_name,
            )
            raise ConversationGenerationError(code=safe_code)

        completed_at = self._clock()
        response_usage = response.usage
        usage = (
            None
            if response_usage is None
            else DomainTokenUsage(
                prompt_tokens=response_usage.input_tokens,
                completion_tokens=response_usage.output_tokens,
                total_tokens=response_usage.total_tokens,
            )
        )
        await self._complete_turn(
            conversation_id=command.conversation_id,
            turn_id=turn_id,
            content=response.text,
            provider_name=response.provider_name,
            model_name=response.model_name,
            finish_reason=response.finish_reason.value,
            usage=usage,
            completed_at=completed_at,
        )
        return ConversationChatResult(
            conversation_id=command.conversation_id,
            turn_id=turn_id,
            request_id=request_id,
            answer=response.text,
            provider_name=response.provider_name,
            model_name=response.model_name,
            finish_reason=response.finish_reason.value,
            usage=TokenUsageView(
                input_tokens=(
                    response_usage.input_tokens if response_usage is not None else None
                ),
                output_tokens=(
                    response_usage.output_tokens if response_usage is not None else None
                ),
                total_tokens=(
                    response_usage.total_tokens if response_usage is not None else None
                ),
            ),
            completed_at=completed_at,
        )

    async def _start_pending_turn(
        self,
        *,
        command: ConversationChatCommand,
        request_id: str,
    ) -> tuple[UUID, Message]:
        async with self._unit_of_work_factory() as unit_of_work:
            conversation = await unit_of_work.conversation_repository.get_for_update(
                command.conversation_id
            )
            if conversation is None:
                raise ConversationNotFoundError(command.conversation_id)
            turn = conversation.start_turn(
                user_content=command.user_content,
                request_id=request_id,
                idempotency_key=command.idempotency_key,
                created_at=self._clock(),
            )
            await unit_of_work.conversation_repository.save(conversation)
            await unit_of_work.turn_repository.add(turn)
            await unit_of_work.message_repository.add(turn.user_message)
            await unit_of_work.commit()
            return turn.id, turn.user_message

    async def _load_completed_history(
        self,
        conversation_id: UUID,
        *,
        limit: int,
    ) -> tuple[Message, ...]:
        async with self._unit_of_work_factory() as unit_of_work:
            messages = (
                await unit_of_work.message_repository
                .list_recent_completed_for_context(
                    conversation_id,
                    limit=limit,
                )
            )
            return tuple(messages)

    async def _complete_turn(
        self,
        *,
        conversation_id: UUID,
        turn_id: UUID,
        content: str,
        provider_name: str,
        model_name: str,
        finish_reason: str,
        usage: DomainTokenUsage | None,
        completed_at: datetime,
    ) -> None:
        async with self._unit_of_work_factory() as unit_of_work:
            conversation = await unit_of_work.conversation_repository.get_for_update(
                conversation_id
            )
            if conversation is None:
                raise ConversationNotFoundError(conversation_id)
            turn = conversation.complete_turn(
                turn_id,
                assistant_content=content,
                provider_name=provider_name,
                model_name=model_name,
                finish_reason=finish_reason,
                usage=usage,
                completed_at=completed_at,
            )
            await unit_of_work.conversation_repository.save(conversation)
            await unit_of_work.turn_repository.save(turn)
            assert turn.assistant_message is not None
            await unit_of_work.message_repository.add(turn.assistant_message)
            await unit_of_work.commit()

    async def _best_effort_fail(
        self,
        *,
        conversation_id: UUID,
        turn_id: UUID,
        safe_error_code: str,
        provider_name: str | None,
        model_name: str | None,
    ) -> None:
        try:
            async with self._unit_of_work_factory() as unit_of_work:
                conversation = (
                    await unit_of_work.conversation_repository.get_for_update(
                        conversation_id
                    )
                )
                if conversation is None:
                    return
                turn = self._find_turn(conversation, turn_id)
                if turn.status is not TurnStatus.PENDING:
                    return
                conversation.fail_turn(
                    turn_id,
                    safe_error_code=safe_error_code,
                    provider_name=provider_name,
                    model_name=model_name,
                    completed_at=self._clock(),
                )
                await unit_of_work.conversation_repository.save(conversation)
                await unit_of_work.turn_repository.save(turn)
                await unit_of_work.commit()
        except (Exception, asyncio.CancelledError):
            return

    async def _best_effort_cancel(
        self,
        *,
        conversation_id: UUID,
        turn_id: UUID,
    ) -> None:
        try:
            async with self._unit_of_work_factory() as unit_of_work:
                conversation = (
                    await unit_of_work.conversation_repository.get_for_update(
                        conversation_id
                    )
                )
                if conversation is None:
                    return
                turn = self._find_turn(conversation, turn_id)
                if turn.status is not TurnStatus.PENDING:
                    return
                conversation.cancel_turn(turn_id, completed_at=self._clock())
                await unit_of_work.conversation_repository.save(conversation)
                await unit_of_work.turn_repository.save(turn)
                await unit_of_work.commit()
        except (Exception, asyncio.CancelledError):
            return

    @staticmethod
    def _find_turn(
        conversation: Conversation,
        turn_id: UUID,
    ) -> ConversationTurn:
        for turn in conversation.turns:
            if turn.id == turn_id:
                return turn
        raise TurnNotFoundError("Turn is not part of the conversation")
