"""Shared offline fixtures for conversation HTTP adapter tests."""

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, Mock
from uuid import UUID

from fastapi import FastAPI

from app.api.dependencies.conversations import (
    get_conversation_chat_service,
    get_conversation_command_service,
    get_conversation_query_service,
)
from app.api.dependencies.database import get_database_manager
from app.api.router import api_router
from app.application.conversations import (
    ConversationChatResult,
    ConversationChatService,
    ConversationCommandService,
    ConversationPage,
    ConversationQueryService,
    ConversationView,
    MessagePage,
    MessageView,
    TokenUsageView,
)
from app.core.exceptions import register_exception_handlers
from app.domain.conversations import (
    ConversationStatus,
    MessageRole,
    TurnStatus,
)


NOW = datetime(2026, 9, 1, 14, 0, tzinfo=UTC)
CONVERSATION_ID = UUID("11111111-1111-4111-8111-111111111111")
TURN_ID = UUID("22222222-2222-4222-8222-222222222222")
USER_MESSAGE_ID = UUID("33333333-3333-4333-8333-333333333333")
ASSISTANT_MESSAGE_ID = UUID("44444444-4444-4444-8444-444444444444")


def conversation_view(
    *,
    status: ConversationStatus = ConversationStatus.ACTIVE,
) -> ConversationView:
    archived_at = NOW + timedelta(minutes=5) if status is ConversationStatus.ARCHIVED else None
    return ConversationView(
        id=CONVERSATION_ID,
        title="Offline conversation",
        status=status,
        created_at=NOW,
        updated_at=archived_at or NOW,
        archived_at=archived_at,
    )


def message_views() -> tuple[MessageView, MessageView]:
    return (
        MessageView(
            id=USER_MESSAGE_ID,
            conversation_id=CONVERSATION_ID,
            turn_id=TURN_ID,
            role=MessageRole.USER,
            content="Offline question",
            sequence=1,
            created_at=NOW + timedelta(seconds=1),
        ),
        MessageView(
            id=ASSISTANT_MESSAGE_ID,
            conversation_id=CONVERSATION_ID,
            turn_id=TURN_ID,
            role=MessageRole.ASSISTANT,
            content="Offline answer",
            sequence=2,
            created_at=NOW + timedelta(seconds=2),
        ),
    )


def chat_result() -> ConversationChatResult:
    user_message, assistant_message = message_views()
    return ConversationChatResult(
        conversation_id=CONVERSATION_ID,
        turn_id=TURN_ID,
        request_id="request-001",
        answer=assistant_message.content,
        user_message=user_message,
        assistant_message=assistant_message,
        provider_name="mock",
        model_name="mock-default",
        finish_reason="stop",
        usage=TokenUsageView(
            input_tokens=3,
            output_tokens=2,
            total_tokens=5,
        ),
        status=TurnStatus.COMPLETED,
        completed_at=assistant_message.created_at,
    )


def build_test_services() -> tuple[
    ConversationCommandService,
    ConversationQueryService,
    ConversationChatService,
]:
    command_service = Mock(spec=ConversationCommandService)
    command_service.create_conversation = AsyncMock(return_value=conversation_view())
    command_service.archive_conversation = AsyncMock(
        return_value=conversation_view(status=ConversationStatus.ARCHIVED)
    )

    query_service = Mock(spec=ConversationQueryService)
    query_service.get_conversation = AsyncMock(return_value=conversation_view())
    query_service.list_conversations = AsyncMock(
        return_value=ConversationPage(
            items=(conversation_view(),),
            offset=0,
            limit=50,
        )
    )
    query_service.list_messages = AsyncMock(
        return_value=MessagePage(
            items=message_views(),
            after_sequence=None,
            limit=100,
            next_sequence=2,
        )
    )

    chat_service = Mock(spec=ConversationChatService)
    chat_service.complete = AsyncMock(return_value=chat_result())
    return command_service, query_service, chat_service


def build_test_application() -> tuple[
    FastAPI,
    ConversationCommandService,
    ConversationQueryService,
    ConversationChatService,
]:
    application = FastAPI()
    register_exception_handlers(application)
    application.include_router(api_router)
    command_service, query_service, chat_service = build_test_services()
    application.dependency_overrides[get_conversation_command_service] = (
        lambda: command_service
    )
    application.dependency_overrides[get_conversation_query_service] = (
        lambda: query_service
    )
    application.dependency_overrides[get_conversation_chat_service] = (
        lambda: chat_service
    )
    database_manager = Mock()
    database_manager.check_connection = AsyncMock()
    application.dependency_overrides[get_database_manager] = lambda: database_manager
    return application, command_service, query_service, chat_service
