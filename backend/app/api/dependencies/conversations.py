"""FastAPI dependency wiring for persistent conversation use cases."""

from collections.abc import Callable

from fastapi import Request

from app.api.dependencies.database import get_database_manager
from app.application.conversations import (
    ConversationChatService,
    ConversationCommandService,
    ConversationQueryService,
    ConversationUnitOfWork,
)
from app.llm.service import LLMService
from app.repositories.unit_of_work import SqlAlchemyConversationUnitOfWork


type ConversationUnitOfWorkFactory = Callable[[], ConversationUnitOfWork]


def _unit_of_work_factory(request: Request) -> ConversationUnitOfWorkFactory:
    database_manager = get_database_manager(request)

    def create_unit_of_work() -> ConversationUnitOfWork:
        return SqlAlchemyConversationUnitOfWork(database_manager.session)

    return create_unit_of_work


def get_conversation_command_service(
    request: Request,
) -> ConversationCommandService:
    """Build command use cases from the request-owned application resources."""

    return ConversationCommandService(
        unit_of_work_factory=_unit_of_work_factory(request)
    )


def get_conversation_query_service(
    request: Request,
) -> ConversationQueryService:
    """Build query use cases without exposing persistence to the router."""

    return ConversationQueryService(
        unit_of_work_factory=_unit_of_work_factory(request)
    )


def get_conversation_chat_service(
    request: Request,
) -> ConversationChatService:
    """Build persistent non-streaming chat from application-facing ports."""

    llm_service = getattr(request.app.state, "llm_service", None)
    if not isinstance(llm_service, LLMService):
        raise RuntimeError("LLM service is not initialized")
    return ConversationChatService(
        unit_of_work_factory=_unit_of_work_factory(request),
        llm_service=llm_service,
    )


__all__ = (
    "get_conversation_chat_service",
    "get_conversation_command_service",
    "get_conversation_query_service",
)
