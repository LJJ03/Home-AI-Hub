"""Offline tests for Conversation dependency composition."""

from unittest.mock import Mock, patch

from fastapi import FastAPI
from starlette.requests import Request

from app.api.dependencies.conversations import (
    get_conversation_chat_service,
    get_conversation_command_service,
    get_conversation_query_service,
)
from app.application.conversations import (
    ConversationChatService,
    ConversationCommandService,
    ConversationQueryService,
)
from app.llm.service import LLMService
from app.repositories.unit_of_work import SqlAlchemyConversationUnitOfWork


def _request(application: FastAPI) -> Request:
    return Request(
        {
            "type": "http",
            "app": application,
            "method": "GET",
            "path": "/",
            "headers": [],
        }
    )


def test_dependencies_build_services_from_lifespan_owned_resources() -> None:
    application = FastAPI()
    application.state.llm_service = Mock(spec=LLMService)
    database_manager = Mock()
    database_manager.session = Mock()
    request = _request(application)

    with patch(
        "app.api.dependencies.conversations.get_database_manager",
        return_value=database_manager,
    ):
        command_service = get_conversation_command_service(request)
        query_service = get_conversation_query_service(request)
        chat_service = get_conversation_chat_service(request)

    assert isinstance(command_service, ConversationCommandService)
    assert isinstance(query_service, ConversationQueryService)
    assert isinstance(chat_service, ConversationChatService)
    assert isinstance(
        command_service._unit_of_work_factory(),
        SqlAlchemyConversationUnitOfWork,
    )
    assert chat_service._llm_service is application.state.llm_service
